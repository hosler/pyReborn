"""NPCPROP 33 (alignment) is parsed and stored as ``ap``.

The wire format is one gchar (reborn_protocol.props.NPC_PROPS, id 33). A
hand-built packet: npc id 7, ALIGNMENT 80, then NICKNAME "a", which proves the
parser consumed exactly one byte for the alignment.
"""

from pyreborn.packet_codec.level import parse_npc_props


def _gchar(value):
    return bytes(((value + 32) & 0xFF,))


def test_alignment_is_parsed_and_the_next_prop_still_reads():
    # Mutation: delete the `33: _set('ap')` handler in packet_codec/level.py
    # -> 'ap' is missing from the parsed props.
    data = (_gchar(0) + _gchar(0) + _gchar(7)
            + _gchar(20) + _gchar(1) + b"a"
            + _gchar(33) + _gchar(80))
    props = parse_npc_props(data, 5, colors_len_known=True)
    assert props == {"id": 7, "nickname": "a", "ap": 80}


def test_alignment_between_two_props_consumes_exactly_one_byte():
    # nickname "a", ALIGNMENT 80, BODYIMAGE (35) "b.png": hand-written bytes.
    # Mutation: make the 33 handler consume 2 bytes (or none) -> the body
    # image is misread or lost.
    data = (bytes((32, 32, 7 + 32))
            + bytes((20 + 32, 1 + 32)) + b"a"
            + bytes((33 + 32, 80 + 32))
            + bytes((35 + 32, 5 + 32)) + b"b.png")
    props = parse_npc_props(data, 5, colors_len_known=True)
    assert props == {"id": 7, "nickname": "a", "ap": 80, "bodyimage": "b.png"}
