"""Fatal attributed hurt reports one killer ID per life."""

from types import SimpleNamespace

import pytest
from reborn_protocol import PacketBuilder, PLPROP

from pyreborn import Client
from pyreborn.handlers.combat import handle_hurt_player
from pyreborn.handlers.entities import handle_player_props
from pyreborn.packets import PacketID, build_claim_pker


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr('time.time', lambda: 100.0)
    client = Client('localhost', 14900)
    client.sent = []
    client._protocol = SimpleNamespace(
        connected=True,
        send_packet=lambda p, d=b'': client.sent.append((p, d)) or True)
    client._authenticated = True
    client._current_level_name = client._tiles_level_name = 'combat.nw'
    client.tiles = [0] * 4096
    client.levels['combat.nw'] = client.tiles
    client.player.id = 7
    client.players[300] = {'ap': 50}
    return client


def claims(client):
    return [data for packet, data in client.sent if packet == PacketID.PLI_CLAIMPKER]


def test_builder_and_sender(client):
    assert PacketID.PLI_CLAIMPKER == 14
    assert build_claim_pker(300) == b'"L'
    assert client.send_claim_pker(300)
    assert claims(client) == [b'"L']


@pytest.mark.parametrize('connected,authenticated', [(False, True), (True, False)])
def test_sender_requires_session(client, connected, authenticated):
    client._protocol.connected = connected
    client._authenticated = authenticated
    assert not client.send_claim_pker(300)
    assert not client.sent


@pytest.mark.parametrize('attacker,hearts,expected', [
    (300, 0.5, [b'"L']), (7, 0.5, []), (999, 0.5, []),
    (0, 0.5, []), (300, 1.0, []),
])
def test_explosion_claims_only_known_other_on_death(client, attacker, hearts, expected):
    client.player.set_hearts(hearts)
    assert client._hurt_by_explosion(SimpleNamespace(sprite_row=0), 1, attacker)
    assert claims(client) == expected


def hurt_packet(attacker=300):
    return (PacketBuilder().write_gshort(attacker).write_gchar(1)
            .write_gchar(0).write_gchar(1).build())


def test_hurt_handler_and_explosion_share_once_per_death_guard(client):
    client.player.set_hearts(0.5)
    client._hurt_by_explosion(SimpleNamespace(sprite_row=0), 1, 300)
    handle_hurt_player(client, hurt_packet())
    assert not client._claim_pker_if_dead(300)
    assert claims(client) == [b'"L']

    # Authoritative respawn HP clears the flag even before the next hurt.
    props = PacketBuilder().write_gchar(PLPROP.CURPOWER).write_gchar(1).build()
    handle_player_props(client, props)
    assert not client._pker_claimed
    handle_hurt_player(client, hurt_packet())
    assert claims(client) == [b'"L', b'"L']
    handle_hurt_player(client, hurt_packet())
    assert claims(client) == [b'"L', b'"L']


def test_local_healing_starts_another_claimable_life(client):
    client.player.set_hearts(0)
    assert client._claim_pker_if_dead(300)
    assert client.send_hearts(0.5)
    assert not client._pker_claimed
    handle_hurt_player(client, hurt_packet())
    assert len(claims(client)) == 2


def test_local_arrow_death_claims_killer(client):
    client.player.set_hearts(0.5)
    client._resolve_pending_arrow_hit({'owner_id': 300, 'dx': 1, 'dy': 0})
    assert client.player.hearts == 0
    assert claims(client) == [b'"L']


def test_kills_count_reaches_local_player(client):
    props = (PacketBuilder().write_gchar(PLPROP.KILLSCOUNT)
             .write_gint3(301).build())
    handle_player_props(client, props)
    assert client.player.kills == 301
