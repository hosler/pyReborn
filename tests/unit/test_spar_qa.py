"""Offline validation of the spar fixture and live-test failure guards."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from reborn_protocol import PLPROP
from reborn_protocol.props import PLAYER_PROPS, encode_value

from game_tester import reporter, tier2_tests as tier2
from game_tester.spar_fixture import SPAR_LEVEL, spar_level_text, write_spar_fixture
from game_tester.test_scenarios import reset_account_position
from pyreborn import Client
from pyreborn.handlers.entities import handle_player_props
from pygserver.config import ServerConfig
from pygserver.level import Level
from pygserver.server import GameServer


@pytest.mark.asyncio
async def test_fixture_registers_spar_flag_only_when_npc_is_registered(tmp_path):
    assert write_spar_fixture(tmp_path)
    assert not write_spar_fixture(tmp_path)
    assert (tmp_path / SPAR_LEVEL).read_text() == spar_level_text()
    level = Level.load(str(tmp_path / SPAR_LEVEL))
    assert level.get_tile(30, 30) == 0
    assert len(level.get_npc_defs()) == 1
    assert not level.is_sparring_zone  # Discovering the file alone is insufficient.
    server = GameServer(ServerConfig())
    await server._register_level_features(level)
    assert level.is_sparring_zone
    assert [npc.client_script for npc in level.get_npcs()] == ['sparringzone']


def test_rating_wire_reaches_player():
    client = Client()
    handle_player_props(client, bytes([PLPROP.DEATHSCOUNT + 32]) +
                        encode_value(PLAYER_PROPS[PLPROP.DEATHSCOUNT], 1) +
                        bytes([PLPROP.RATING + 32]) +
                        encode_value(PLAYER_PROPS[PLPROP.RATING], (1662, 290)))
    assert (client.player.rating, client.player.rating_deviation) == (1662, 290)
    assert client.player.deaths == 1


def test_account_fixture_resets_both_rating_formats(tmp_path, monkeypatch):
    monkeypatch.setenv('PYGSERVER_ACCOUNTS_DIR', str(tmp_path))
    monkeypatch.setenv('GSERVER_ACCOUNTS_DIR', str(tmp_path))
    path = tmp_path / 'testbot1.json'
    path.write_text(json.dumps(dict(elo_rating=1800, elo_deviation=80, last_spar_time=123)))
    flat = tmp_path / 'testbot1.txt'
    flat.write_text('GRACC001\nRATING 1800\nDEVIATION 80\nLASTSPARTIME 123\n')
    reset_account_position('testbot1')
    data = json.loads(path.read_text())
    assert (data['elo_rating'], data['elo_deviation'], data['last_spar_time']) == (1500, 350, 0)
    assert 'RATING 1500\nDEVIATION 350\nLASTSPARTIME 0\n' in flat.read_text()


def test_spar_skips_when_loopback_alias_cannot_bind(monkeypatch):
    monkeypatch.setattr(tier2.socket, 'socket', Mock(side_effect=OSError('cannot bind')))
    result = tier2.test_spar_rating_updates()
    assert result.skipped and not result.passed
    assert '127.0.0.2' in result.details and 'cannot bind' in result.details


def test_spar_missing_fixture_requests_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('PYGSERVER_LEVELS_DIR', str(tmp_path))
    monkeypatch.setattr(tier2.socket, 'socket', MagicMock())
    connect = Mock(side_effect=AssertionError('must not connect'))
    monkeypatch.setattr(tier2, 'GameBot', connect)
    result = tier2.test_spar_rating_updates()
    assert result.skipped and not result.passed
    assert 'restart' in result.details and (tmp_path / SPAR_LEVEL).exists()


def test_skips_are_reported_separately(tmp_path, capsys):
    report = reporter.TestReporter()
    report.add_result('unavailable', False, 0, 'cannot bind 127.0.0.2', skipped=True)
    report.add_result('working', True, 0)
    assert not report.has_failures()
    assert report.get_pass_rate() == 1.0
    summary = report.to_dict()['summary']
    assert (summary['passed'], summary['failed'], summary['skipped']) == (1, 0, 1)
    report.print_summary()
    assert '[SKIP]' in capsys.readouterr().out
    path = tmp_path / 'report.html'
    report.save_html(str(path))
    assert 'test skipped' in path.read_text()


@pytest.mark.parametrize('same_ip,behavior,passes', [
    (False, 'ratings', True),
    (True, 'unchanged', True),
    (False, 'unchanged', False),
    (True, 'ratings', False),
    (False, 'kills', False),
    (True, 'no_death_confirmation', False),
])
def test_live_assertions_require_death_rating_delivery_and_no_kills(
        tmp_path, monkeypatch, same_ip, behavior, passes):
    write_spar_fixture(tmp_path)
    monkeypatch.setenv('PYGSERVER_LEVELS_DIR', str(tmp_path))
    monkeypatch.setattr(tier2.socket, 'socket', MagicMock())
    monkeypatch.setattr(tier2, '_pump', lambda *args, **kwargs: None)
    monkeypatch.setattr('game_tester.test_scenarios.reset_account_position', Mock())
    clients = [Client(), Client()]
    bots = []
    for i, client in enumerate(clients):
        client.player.id = i + 1
        client.player.rating, client.player.rating_deviation = 1500, 350
        client._current_level_name = client._tiles_level_name = SPAR_LEVEL
        client.tiles = [0] * 4096
        client.npcs[1] = {'_level': SPAR_LEVEL, 'script': 'sparringzone'}
        client.players[2 - i] = {}
        client.warp_to_level = Mock(return_value=True)
        client.send_hearts = Mock(return_value=True)
        bots.append(SimpleNamespace(client=client, connect=lambda: True,
                                    disconnect=Mock()))

    def kill(*args, **kwargs):
        clients[1].player.hearts = 0
        if behavior != 'no_death_confirmation':
            clients[1].player.deaths += 1
        if behavior == 'kills':
            clients[0].player.kills += 1
        if behavior in ('ratings', 'kills'):
            for client, value in zip(clients, [(1662, 290), (1337, 290)]):
                data = bytes([PLPROP.RATING + 32]) + encode_value(
                    PLAYER_PROPS[PLPROP.RATING], value)
                handle_player_props(client, data)
                client.on_packet[tier2.PacketID.PLO_PLAYERPROPS](data)

    clients[0].put_bomb = kill
    factory = Mock(side_effect=bots)
    monkeypatch.setattr(tier2, 'GameBot', factory)
    result = tier2._spar_rating_test('localhost', 14900, ('a', 'b'), same_ip)
    assert not result.skipped
    assert result.passed is passes, result.details
    assert factory.call_args_list[0].kwargs['source_address'] == '127.0.0.1'
    assert factory.call_args_list[1].kwargs['source_address'] == (
        '127.0.0.1' if same_ip else '127.0.0.2')
    assert all(bot.disconnect.called for bot in bots)
