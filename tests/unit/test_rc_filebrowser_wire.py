"""Hand-built RC response fixtures for reference wire compatibility."""

from pyreborn.packet_codec.rc import (
    parse_rc_filebrowser_dir,
    parse_rc_filebrowser_dirlist,
)


def _gchar(value):
    return bytes([value + 32])


def _gint5(value):
    return bytes([
        (value >> 28) + 32,
        ((value >> 21) & 0x7f) + 32,
        ((value >> 14) & 0x7f) + 32,
        ((value >> 7) & 0x7f) + 32,
        (value & 0x7f) + 32,
    ])


def _gstring(value):
    raw = value.encode("latin-1")
    return _gchar(len(raw)) + raw


def test_parse_filebrowser_folder_rights_csv():
    payload = b'"rw levels/*","r folder,with comma/*","r quoted""name/*"'
    assert parse_rc_filebrowser_dirlist(payload) == {
        "folders": [
            "rw levels/*",
            "r folder,with comma/*",
            'r quoted"name/*',
        ]
    }


def test_parse_filebrowser_directory_blocks():
    first = _gstring("map.nw") + _gstring("rw") + _gint5(42) + _gint5(1000)
    second = _gstring("images/") + _gstring("r") + _gint5(0) + _gint5(2000)
    payload = (
        _gstring("levels")
        + b" " + _gchar(len(first)) + first
        + b" " + _gchar(len(second)) + second
    )

    assert parse_rc_filebrowser_dir(payload) == {
        "folder": "levels",
        "files": [
            {"name": "map.nw", "rights": "rw", "size": 42, "modified": 1000},
            {"name": "images/", "rights": "r", "size": 0, "modified": 2000},
        ],
    }

