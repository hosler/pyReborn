"""The COLORS width in force serves reading AND writing (pyreborn.colors_width).

Rule: PLO_NEWWORLDMODE (177) -> 8 and known; PLO_KINGDOMSMODE (176) -> 5;
otherwise the session's parse evidence (colors_seen_5 / colors_seen_8) decides,
and with none the reference default 5 applies. The width a client WRITES in
PLI_PLAYERPROPS and in an RC prop-set stream is that same width, so a server in
normal mode (reads 5) and one in new-world mode (reads 8) both parse it.
"""

import pytest

from pyreborn.client import Client
from pyreborn.colors_width import colors_len_in_force, colors_width_policy
from pyreborn.packets import PacketID, parse_player_props
from pyreborn.rc_client import RCClient


def gchar(value):
    return bytes(((value + 32) & 0xFF,))


def colors(values):
    return b''.join(gchar(v) for v in values)


NEWWORLD = [1, 2, 3, 4, 5, 6, 7, 8]


class _Protocol:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b''):
        self.sent.append((packet_id, data))
        return True


def _client(cls=Client, version='6.037'):
    client = cls(version=version)
    client._protocol = _Protocol()
    client._authenticated = True
    client._remember_appearance = lambda **fields: None
    client._apply_login_appearance = lambda props: None
    return client


def _feed_colors(client, values):
    client._handle_packet(PacketID.PLO_PLAYERPROPS, gchar(13) + colors(values))


# --- incoming evidence -------------------------------------------------------

def test_177_is_decisive_for_eight_even_against_five_byte_evidence():
    client = _client()
    _feed_colors(client, [1, 2, 3, 4, 5])
    assert colors_width_policy(client) == (5, False)
    client._handle_packet(PacketID.PLO_NEWWORLDMODE, b'')
    assert colors_width_policy(client) == (8, True)


def test_no_177_and_no_evidence_is_the_reference_default_five():
    for version in ('2.22', '6.037'):
        assert colors_width_policy(_client(version=version)) == (5, False)


def test_no_177_does_not_force_five_on_a_server_that_sends_eight():
    """Evidence rule kept: a server writing 8 bytes without 177 is followed."""
    client = _client()
    _feed_colors(client, NEWWORLD)
    _feed_colors(client, NEWWORLD)
    assert client.server_mode == ''
    assert colors_width_policy(client) == (8, False)
    assert client.player.colors[:8] == NEWWORLD


def test_kingdoms_mode_is_five_but_not_known():
    client = _client()
    client._handle_packet(PacketID.PLO_KINGDOMSMODE, b'')
    assert colors_width_policy(client) == (5, False)


def test_reconnect_drops_the_width_in_force(monkeypatch):
    client = _client()
    client._handle_packet(PacketID.PLO_NEWWORLDMODE, b'')
    assert colors_len_in_force(client) == 8
    monkeypatch.setattr(client._protocol, 'connect', lambda: True, raising=False)
    client.server_mode = ''
    client.prop_parse_diagnostics.clear()
    assert colors_len_in_force(client) == 5


# --- outgoing PLI_PLAYERPROPS ------------------------------------------------

@pytest.mark.parametrize('mode,width', [('', 5), ('newworld', 8)])
def test_sent_player_props_use_the_width_in_force(mode, width):
    client = _client()
    if mode:
        client._handle_packet(PacketID.PLO_NEWWORLDMODE, b'')
    assert client.send_colors(range(1, 9))
    packet_id, data = client._protocol.sent[-1]
    assert packet_id == PacketID.PLI_PLAYERPROPS
    assert data == gchar(13) + colors(range(1, width + 1))
    # What a server of that mode reads back is exactly the colors it was sent.
    parsed = parse_player_props(data, width, colors_len_known=True)
    assert parsed['colors'] == list(range(1, width + 1))
    assert client.player.colors == list(range(1, width + 1))


def test_sent_width_follows_evidence_without_177():
    client = _client()
    _feed_colors(client, NEWWORLD)
    _feed_colors(client, NEWWORLD)
    assert client.send_colors(range(1, 9))
    assert client._protocol.sent[-1][1] == gchar(13) + colors(range(1, 9))


def test_what_is_received_and_what_is_sent_agree_in_both_modes():
    for announce, width in ((False, 5), (True, 8)):
        client = _client()
        if announce:
            client._handle_packet(PacketID.PLO_NEWWORLDMODE, b'')
        _feed_colors(client, list(range(1, width + 1)))
        assert client.player.colors[:width] == list(range(1, width + 1))
        assert colors_len_in_force(client) == width
        client.send_colors(range(1, 9))
        assert len(client._protocol.sent[-1][1]) == 1 + width


# --- RC prop-set -------------------------------------------------------------

@pytest.mark.parametrize('announce,width', [(False, 5), (True, 8)])
def test_rc_prop_set_stream_uses_the_connection_width(announce, width):
    rc = _client(RCClient)
    if announce:
        rc._handle_packet(PacketID.PLO_NEWWORLDMODE, b'')
    stream = rc.encode_player_props({13: range(1, 9), 15: 20.0})
    assert stream[:1] == gchar(13)
    assert stream[1:1 + width] == colors(range(1, width + 1))
    assert stream[1 + width:2 + width] == gchar(15)       # ascending, no padding
    assert len(stream) == 1 + width + 2
    assert rc.set_player_props(7, props=stream)
    packet_id, data = rc._protocol.sent[-1]
    assert packet_id == PacketID.PLI_RC_PLAYERPROPSSET
    assert stream in data


def test_rc_prop_stream_orders_ids_ascending():
    rc = _client(RCClient)
    stream = rc.encode_player_props({15: 20.0, 13: [1, 2, 3, 4, 5]})
    assert stream[:1] == gchar(13)


# --- NPC props ---------------------------------------------------------------

def gint3(value):
    return gchar((value >> 14) & 0x7F) + gchar((value >> 7) & 0x7F) + gchar(value & 0x7F)


def test_client_never_sends_npc_colors():
    """The reference reads NPC colors from a client at 5 bytes always, and the
    client builds no NPC prop carrying them: only attribute strings go out."""
    from pyreborn.packets import build_npc_props
    data = build_npc_props(7, 'P1', 'x')
    assert gchar(19) not in data[4:5]            # the one prop id byte after the id
    assert data[4:5] == gchar(36)


@pytest.mark.parametrize('announce,width', [(False, 5), (True, 8)])
def test_incoming_npc_colors_follow_the_mode_width(announce, width):
    client = _client()
    if announce:
        client._handle_packet(PacketID.PLO_NEWWORLDMODE, b'')
    values = list(range(1, width + 1))
    client._handle_packet(PacketID.PLO_NPCPROPS,
                          gint3(7) + gchar(19) + colors(values)
                          + gchar(20) + gchar(1) + b'a')
    assert client.npcs[7]['colors'] == values
    assert client.npcs[7]['nickname'] == 'a'
