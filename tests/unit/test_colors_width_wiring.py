"""Session wiring of the COLORS width decision (see test_colors_width.py).

Only PLO_NEWWORLDMODE (177) makes the width "known" (GServer-v2
Player.cpp:751-752 sends it before the first PLO_PLAYERPROPS,
PlayerClient.cpp:547); its absence proves nothing, because pygserver writes
8-byte COLORS without ever sending it. Everything else rides the parser's
per-session evidence, which a reconnect must reset.
"""

from pyreborn.client import Client
from pyreborn.packets import PacketID


def gchar(value: int) -> bytes:
    return bytes(((value + 32) & 0xFF,))


def gshort(value: int) -> bytes:
    return gchar(value >> 7) + gchar(value & 0x7F)


def gint3(value: int) -> bytes:
    return gchar((value >> 14) & 0x7F) + gchar((value >> 7) & 0x7F) + gchar(value & 0x7F)


def colors(values):
    return b''.join(gchar(v) for v in values)


CLASSIC = [1, 2, 3, 4, 5]
# Reads cleanly at 5 too: colors[5:8] = [14, 2, 44] is a valid ID(14) prop.
AMBIGUOUS_NEWWORLD = [1, 2, 3, 4, 5, 14, 2, 44]


def _client(version, monkeypatch):
    client = Client(version=version)
    seen = []
    monkeypatch.setattr(client, '_apply_login_appearance', seen.append)
    return client, seen


def test_newworld_announcement_makes_the_width_known(monkeypatch):
    """A 2.22 client prefers 5; after 177 an ambiguous stream parses at 8,
    and the login look-ahead sees exactly what the handler parsed."""
    client, seen = _client('2.22', monkeypatch)
    client._handle_packet(PacketID.PLO_FULLSTOP2, b'')
    assert client.server_mode == 'newworld'
    client._handle_packet(PacketID.PLO_PLAYERPROPS,
                          gchar(13) + colors(AMBIGUOUS_NEWWORLD))
    assert client.player.colors[:8] == AMBIGUOUS_NEWWORLD
    assert seen and seen[0]['colors'] == AMBIGUOUS_NEWWORLD
    assert 'colors_ambiguous' not in client.prop_parse_diagnostics


def test_no_announcement_is_not_known_classic(monkeypatch):
    """Without 177 the same ambiguous stream from a pygserver-like server is
    resolved by the session's evidence, not by assuming 5."""
    client, _ = _client('2.22', monkeypatch)
    # One unambiguous new-world packet (COLORS last: 8 bytes cannot be 5).
    client._handle_packet(PacketID.PLO_PLAYERPROPS,
                          gchar(13) + colors([1, 2, 3, 4, 5, 6, 7, 8]))
    assert client.prop_parse_diagnostics['width_fallbacks'] == 1
    client._handle_packet(PacketID.PLO_PLAYERPROPS,
                          gchar(13) + colors(AMBIGUOUS_NEWWORLD))
    assert client.player.colors[:8] == AMBIGUOUS_NEWWORLD
    assert client.prop_parse_diagnostics['colors_ambiguous'] == 1


def test_npc_and_other_player_props_share_the_session_evidence(monkeypatch):
    """v6 client against a classic-mode server: a 5-byte COLORS + 1-char NPC
    nickname is ambiguous, and the self-props evidence settles it."""
    client, _ = _client('6.037', monkeypatch)
    client._handle_packet(PacketID.PLO_PLAYERPROPS,
                          gchar(13) + colors(CLASSIC))           # classic evidence
    client._handle_packet(PacketID.PLO_NPCPROPS,
                          gint3(7) + gchar(19) + colors(CLASSIC)
                          + gchar(20) + gchar(1) + b'a')
    npc = client.npcs[7]
    assert npc['colors'] == CLASSIC
    assert npc['nickname'] == 'a'


def test_single_parse_per_login_packet(monkeypatch):
    """The look-ahead reuses the handler's parse: evidence counts once."""
    client, seen = _client('6.037', monkeypatch)
    client._handle_packet(PacketID.PLO_PLAYERPROPS,
                          gchar(13) + colors(CLASSIC) + gchar(15) + gchar(20))
    assert client.prop_parse_diagnostics['width_fallbacks'] == 1
    assert seen[0]['colors'] == CLASSIC


def test_reconnect_resets_mode_and_width_evidence(monkeypatch):
    client, _ = _client('6.037', monkeypatch)
    client._handle_packet(PacketID.PLO_FULLSTOP2, b'')
    client._handle_packet(PacketID.PLO_PLAYERPROPS, gchar(13) + colors(CLASSIC))
    assert client.server_mode == 'newworld'
    assert client.prop_parse_diagnostics['width_fallbacks'] == 1
    monkeypatch.setattr(client._protocol, 'connect', lambda: True)
    assert client.connect()
    assert client.server_mode == ''
    assert client.classic_mode_disabled is False
    assert client.prop_parse_diagnostics == {
        'warnings': 0, 'errors': 0, 'width_fallbacks': 0}
