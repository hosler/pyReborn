"""PLPROP_COLORS (13) / NPCPROP_COLORS (19) width: 5 classic, 8 new-world.

The width is a server-wide mode, not a client-version fact: GServer-v2
PropertySerializers.h:793-796 (`isNewWorldMode() ? 8 : 5`), announced to the
client by PLO_NEWWORLDMODE at Player.cpp:751-752 before the first
PLO_PLAYERPROPS (PlayerClient.cpp:547). A wrong width once broke every 2.22
session, so both widths are pinned here with COLORS last and COLORS followed by
3-, 5- and 8-byte props.

The bug pinned by the "ambiguous" tests: a 5-byte COLORS followed by props
totalling exactly 3 bytes also parses cleanly at 8, silently swallowing those
props into colors[5:8]. Before the fix a v6-preferring caller always took that
false-clean parse.
"""

import random

import pytest

from reborn_protocol.props import NPC_PROPS, PLAYER_PROPS, encode_value
from pyreborn.client import Client
from pyreborn.packets import (
    PacketID,
    parse_npc_props,
    parse_other_player,
    parse_player_props,
)


def gchar(value: int) -> bytes:
    return bytes(((value + 32) & 0xFF,))


def gstring(text: str) -> bytes:
    return gchar(len(text)) + text.encode('latin-1')


def gshort(value: int) -> bytes:
    return gchar(value >> 7) + gchar(value & 0x7F)


def gint3(value: int) -> bytes:
    return gchar((value >> 14) & 0x7F) + gchar((value >> 7) & 0x7F) + gchar(value & 0x7F)


CLASSIC_COLORS = [1, 2, 3, 4, 5]
# Values at 5..7 that cannot read as an ascending prop id after COLORS, so a
# wrong 5-width parse of these is never clean.
NEWWORLD_COLORS = [1, 2, 3, 4, 5, 6, 7, 8]


def colors_payload(colors):
    return b''.join(gchar(c) for c in colors)


# --- player props: follower runs of a given total byte length --------------

# (bytes, expected props) after a PLPROP_COLORS. All ids ascend past 13.
PLAYER_FOLLOWERS = {
    'last': (b'', {}),
    3: (gchar(14) + gshort(300), {'id': 300}),                  # ID
    5: (gchar(20) + gstring('abc'), {'level': 'abc'}),          # CURLEVEL
    8: (gchar(20) + gstring('abcdef'), {'level': 'abcdef'}),
}

NPC_FOLLOWERS = {
    'last': (b'', {}),
    3: (gchar(20) + gstring('a'), {'nickname': 'a'}),           # NICKNAME
    5: (gchar(20) + gstring('abc'), {'nickname': 'abc'}),
    8: (gchar(20) + gstring('abcdef'), {'nickname': 'abcdef'}),
}


def player_packet(colors, follower):
    return gchar(13) + colors_payload(colors) + follower


def npc_packet(colors, follower, npc_id=7):
    return gint3(npc_id) + gchar(19) + colors_payload(colors) + follower


def _classic_evidence():
    """A session that has already seen one unambiguous classic packet."""
    diagnostics = {}
    parse_player_props(player_packet(CLASSIC_COLORS, b''), 8, diagnostics)
    assert diagnostics['width_fallbacks'] == 1
    assert diagnostics['colors_seen_5'] == 1
    return diagnostics


def _newworld_evidence():
    diagnostics = {}
    parse_player_props(player_packet(NEWWORLD_COLORS, b''), 5, diagnostics)
    assert diagnostics['width_fallbacks'] == 1
    assert diagnostics['colors_seen_8'] == 1
    return diagnostics


# =============================================================================
# The reproduced bug
# =============================================================================

def test_classic_colors_then_id_is_ambiguous_on_the_wire():
    """The exact G01 stream: `-!"#$%."L` = COLORS(13) [1,2,3,4,5], ID(14) 300.
    Both widths consume it cleanly; at 8 the ID becomes colors[5:8]."""
    data = player_packet(CLASSIC_COLORS, gchar(14) + gshort(300))
    assert data == b'-!"#$%."L'
    diagnostics = {}
    parse_player_props(data, 8, diagnostics)
    assert diagnostics == {'colors_ambiguous': 1}


def test_known_classic_width_keeps_the_following_id():
    data = player_packet(CLASSIC_COLORS, gchar(14) + gshort(300))
    props = parse_player_props(data, 5, colors_len_known=True)
    assert props == {'colors': CLASSIC_COLORS, 'id': 300}


def test_ambiguous_packet_follows_the_sessions_classic_evidence():
    """Unknown width, v6-preferring caller, but this session already saw an
    unambiguous classic COLORS: the ambiguous packet must parse at 5."""
    diagnostics = _classic_evidence()
    data = player_packet(CLASSIC_COLORS, gchar(14) + gshort(300))
    assert parse_player_props(data, 8, diagnostics) == {
        'colors': CLASSIC_COLORS, 'id': 300}
    assert diagnostics['colors_ambiguous'] == 1


def test_npc_classic_colors_then_one_char_nickname():
    """NPC form of the bug: COLORS(19) [1..5] + NICKNAME(20) "a" (3 bytes)."""
    data = npc_packet(CLASSIC_COLORS, gchar(20) + gstring('a'))
    diagnostics = {}
    parse_npc_props(data, 8, diagnostics)
    assert diagnostics == {'colors_ambiguous': 1}

    diagnostics = _classic_evidence()
    assert parse_npc_props(data, 8, diagnostics) == {
        'id': 7, 'colors': CLASSIC_COLORS, 'nickname': 'a'}
    assert parse_npc_props(data, 5, colors_len_known=True) == {
        'id': 7, 'colors': CLASSIC_COLORS, 'nickname': 'a'}


def test_other_player_classic_colors_then_id_with_session_evidence():
    data = gshort(9) + player_packet(CLASSIC_COLORS, gchar(14) + gshort(300))
    diagnostics = _classic_evidence()
    props = parse_other_player(data, 8, diagnostics)
    assert props['colors'] == CLASSIC_COLORS
    assert props['id'] == 9          # packet header wins; ID(14) isn't surfaced


def test_mode_preference_change_keeps_absolute_width_evidence(monkeypatch):
    client = Client(version='6.037')
    client._colors_len = 8   # prior preferring 8, so a 5-byte stream exercises the fallback
    monkeypatch.setattr(client, '_apply_login_appearance', lambda props: None)
    for _ in range(3):
        client._handle_packet(PacketID.PLO_PLAYERPROPS, b'-!"#$%')
    # The first packet falls back; once it is on record the evidence itself
    # sets the preference (colors_width.colors_width_policy), so the next two
    # are confirmed at 5 instead of falling back again.
    assert client.prop_parse_diagnostics['width_fallbacks'] == 1
    assert client.prop_parse_diagnostics['colors_confirmed'] == 2
    assert client.prop_parse_diagnostics['colors_seen_5'] == 3

    client._handle_packet(PacketID.PLO_KINGDOMSMODE, b'')
    assert client.server_mode == 'kingdoms'
    client._handle_packet(PacketID.PLO_NPCPROPS, b"  '3!\"#$%4!a")
    assert client.npcs[7]['colors'] == CLASSIC_COLORS
    assert client.npcs[7]['nickname'] == 'a'
    assert client.prop_parse_diagnostics['colors_seen_5'] == 3
    assert client.prop_parse_diagnostics['colors_ambiguous'] == 1


@pytest.mark.parametrize('preferred,seen_5,seen_8,winner', [
    (5, 2, 1, 5), (8, 2, 1, 5), (5, 1, 2, 8), (8, 1, 2, 8),
    (5, 1, 1, 5), (8, 1, 1, 8),
])
def test_ambiguous_packet_uses_absolute_counts(preferred, seen_5, seen_8, winner):
    diagnostics = {'colors_seen_5': seen_5, 'colors_seen_8': seen_8,
                   'width_fallbacks': 100, 'colors_confirmed': 0}
    data = player_packet(CLASSIC_COLORS, gchar(14) + gshort(300))
    assert len(parse_player_props(data, preferred, diagnostics)['colors']) == winner
    assert diagnostics['colors_seen_5'] == seen_5
    assert diagnostics['colors_seen_8'] == seen_8


def test_newworld_colors_that_read_as_an_id_at_five():
    """The mirror case: colors[5:8] = [14, 2, 44] read at 5 is a clean ID(14).
    A new-world session keeps all eight colors."""
    colors = [1, 2, 3, 4, 5, 14, 2, 44]
    data = player_packet(colors, b'')
    diagnostics = {}
    assert parse_player_props(data, 5, diagnostics) == {
        'colors': [1, 2, 3, 4, 5], 'id': 300}        # no evidence: preferred wins
    assert diagnostics == {'colors_ambiguous': 1}

    diagnostics = _newworld_evidence()
    assert parse_player_props(data, 5, diagnostics) == {'colors': colors}
    assert parse_player_props(data, 8, colors_len_known=True) == {'colors': colors}


def test_one_unambiguous_fluke_does_not_outvote_confirmed_packets():
    diagnostics = {}
    for _ in range(3):      # three clean-only-at-8 packets confirm the preference
        parse_player_props(player_packet(NEWWORLD_COLORS, b''), 8, diagnostics)
    parse_player_props(player_packet(CLASSIC_COLORS, b''), 8, diagnostics)
    assert diagnostics['colors_confirmed'] == 3
    assert diagnostics['width_fallbacks'] == 1
    assert diagnostics['colors_seen_8'] == 3
    assert diagnostics['colors_seen_5'] == 1
    data = player_packet(CLASSIC_COLORS, gchar(14) + gshort(300))
    assert len(parse_player_props(data, 8, diagnostics)['colors']) == 8


def test_known_width_wins_ambiguity_but_not_a_contradiction():
    """Known width: an ambiguous packet is NOT second-guessed, but a packet
    that cannot parse at the known width at all still self-corrects (177 was
    FULLSTOP2 in the older enum, so the announcement could be wrong)."""
    ambiguous = player_packet(CLASSIC_COLORS, gchar(14) + gshort(300))
    diagnostics = _classic_evidence()
    props = parse_player_props(ambiguous, 8, diagnostics, colors_len_known=True)
    assert len(props['colors']) == 8
    assert 'colors_ambiguous' not in diagnostics

    diagnostics = {}
    props = parse_player_props(player_packet(CLASSIC_COLORS, b''), 8,
                               diagnostics, colors_len_known=True)
    assert props == {'colors': CLASSIC_COLORS}
    assert diagnostics == {'known_width_contradicted': 1, 'warnings': 1,
                           'width_fallbacks': 1, 'colors_seen_5': 1}

    diagnostics = {}
    parse_player_props(gchar(13) + gchar(1), 8, diagnostics,
                       colors_len_known=True)
    assert diagnostics == {'errors': 1}


def test_no_colors_prop_needs_no_second_parse():
    diagnostics = {}
    assert parse_player_props(gchar(15) + gchar(20), 8, diagnostics) == {'x': 10.0}
    assert diagnostics == {}


# =============================================================================
# Explicit width x follower matrix (classic AND new-world)
# =============================================================================

@pytest.mark.parametrize('follower', list(PLAYER_FOLLOWERS))
@pytest.mark.parametrize('width,colors', [(5, CLASSIC_COLORS),
                                          (8, NEWWORLD_COLORS)])
def test_player_colors_matrix(width, colors, follower):
    tail, expected = PLAYER_FOLLOWERS[follower]
    data = player_packet(colors, tail)
    want = {'colors': colors, **expected}
    assert parse_player_props(data, width, colors_len_known=True) == want
    # Unknown width, correct preference.
    assert parse_player_props(data, width, {}) == want
    # Unknown width, wrong preference, session evidence of the true mode.
    evidence = _classic_evidence() if width == 5 else _newworld_evidence()
    other = 8 if width == 5 else 5
    assert parse_player_props(data, other, evidence) == want


@pytest.mark.parametrize('follower', list(NPC_FOLLOWERS))
@pytest.mark.parametrize('width,colors', [(5, CLASSIC_COLORS),
                                          (8, NEWWORLD_COLORS)])
def test_npc_colors_matrix(width, colors, follower):
    tail, expected = NPC_FOLLOWERS[follower]
    data = npc_packet(colors, tail)
    want = {'id': 7, 'colors': colors, **expected}
    assert parse_npc_props(data, width, colors_len_known=True) == want
    assert parse_npc_props(data, width, {}) == want
    evidence = _classic_evidence() if width == 5 else _newworld_evidence()
    other = 8 if width == 5 else 5
    assert parse_npc_props(data, other, evidence) == want


@pytest.mark.parametrize('follower', [f for f in PLAYER_FOLLOWERS if f != 3])
def test_unambiguous_followers_self_correct_without_evidence(follower):
    """Every follower except the 3-byte one desyncs the wrong width, so even a
    fresh session (no evidence) gets the classic parse right."""
    tail, expected = PLAYER_FOLLOWERS[follower]
    data = player_packet(CLASSIC_COLORS, tail)
    diagnostics = {}
    assert parse_player_props(data, 8, diagnostics) == {
        'colors': CLASSIC_COLORS, **expected}
    assert diagnostics.get('colors_ambiguous', 0) == 0


# =============================================================================
# Round-trip property: encode (shared encoder) -> decode is the identity
# =============================================================================

def test_colors_round_trip_property():
    """Seeded random streams: COLORS encoded by reborn_protocol's encoder at
    either width, then 0..3 ascending followers. A known width or prior evidence
    returns exactly what was encoded, for player and NPC streams alike."""
    rng = random.Random(0xC0105)
    ambiguous = 0
    for _ in range(500):
        width = rng.choice((5, 8))
        other = 8 if width == 5 else 5
        colors = [rng.randrange(0, 32) for _ in range(width)]
        level = ''.join(rng.choice('abcxyz.nw') for _ in range(rng.randrange(1, 12)))
        player_tail, player_want = b'', {}
        if rng.random() < 0.5:
            pid = rng.randrange(0, 1 << 14)
            player_tail += gchar(14) + encode_value(PLAYER_PROPS[14], pid)
            player_want['id'] = pid
        if rng.random() < 0.5:
            player_tail += gchar(20) + encode_value(PLAYER_PROPS[20], level)
            player_want['level'] = level
        data = (gchar(13) + encode_value(PLAYER_PROPS[13], colors, colors_len=width)
                + player_tail)
        assert parse_player_props(data, width, colors_len_known=True) == {
            'colors': colors, **player_want}
        # With no evidence and the wrong preference, ambiguity is undecidable.
        diagnostics = {f'colors_seen_{width}': 1}
        assert parse_player_props(data, other, diagnostics,
                                   colors_len_known=False) == {
            'colors': colors, **player_want}
        player_ambiguous = diagnostics.get('colors_ambiguous', 0) > 0

        npc_tail, npc_want = b'', {}
        if rng.random() < 0.5:
            npc_tail += gchar(20) + encode_value(NPC_PROPS[20], level)
            npc_want['nickname'] = level
        data = (gint3(7) + gchar(19)
                + encode_value(NPC_PROPS[19], colors, colors_len=width) + npc_tail)
        assert parse_npc_props(data, width, colors_len_known=True) == {
            'id': 7, 'colors': colors, **npc_want}
        diagnostics = {f'colors_seen_{width}': 1}
        assert parse_npc_props(data, other, diagnostics,
                              colors_len_known=False) == {
            'id': 7, 'colors': colors, **npc_want}
        ambiguous += player_ambiguous or diagnostics.get('colors_ambiguous', 0) > 0
    assert ambiguous > 0


# =============================================================================
# NPCPROP_HURTDXDY (16)
# =============================================================================

def test_npc_hurt_dxdy_decodes_with_the_reference_client_scale():
    """GServer-v2 PropertyHurtDxDy::serialize (PropertySerializers.h:636-645)
    writes `>> (char)(d + 32)` per axis, i.e. raw byte = d + 64 with d in
    [-32, 32] (a unit push is d = 32, PropertySerializers.h:608-612). The
    reference client decodes `(raw - 0x40) * 0.0625`
    (Preagonal/FourPlay/quattroplay/src/TServerNPC.cpp:1137-1144,
    TInitStatics.cpp:1245)."""
    # Server-side push dx=+1.0, dy=-0.5 -> d = 32, -16 -> raw 96, 48.
    data = gint3(7) + gchar(16) + bytes((96, 48)) + gchar(18) + gchar(2)
    props = parse_npc_props(data, 5, {})
    assert props['hurt_dx'] == 2.0
    assert props['hurt_dy'] == -1.0
    assert props['sprite'] == 2             # stream stays aligned
    centre = parse_npc_props(gint3(7) + gchar(16) + bytes((64, 64)), 5, {})
    assert (centre['hurt_dx'], centre['hurt_dy']) == (0.0, 0.0)


def test_npc_hurt_dxdy_fixed_vector_from_the_reference_encoder():
    """Bytes from the reference server's CString path: PropertyHurtDxDy(-1.0f,
    0.25f) stores (-32, 8) (PropertySerializers.h:608-612); serialize writes
    `>> (char)(d + 32)` (:644), and CString::writeGChar adds 32
    (GServer-v2/dependencies/gs2lib/src/CString.cpp:1519-1523) ->
    b'\\x20\\x48'."""
    data = gint3(1) + gchar(16) + b'\x20\x48'
    props = parse_npc_props(data, 5, {})
    assert props['hurt_dx'] == -2.0
    assert props['hurt_dy'] == 0.5
