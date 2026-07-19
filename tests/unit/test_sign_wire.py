"""Checks for decoding the classic level-sign wire encoding."""

import pytest

from pyreborn.packets import parse_level_sign


@pytest.mark.parametrize(
    ("encoded", "text"),
    (
        (bytes((58, 118, 59, 60, 128)), "a#bc\n"),
        (
            bytes((54, 62, 69, 60, 72, 70, 62, 118, 59, 77, 72, 118,
                   59, 49, 62, 59, 72, 75, 71, 94, 128)),
            "Welcome#bto#bReborn!\n",
        ),
    ),
)
def test_level_sign_decodes_classic_wire(encoded, text):
    assert parse_level_sign(bytes((86, 79)) + encoded)["text"] == text
