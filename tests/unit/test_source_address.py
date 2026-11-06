"""Native source-IP plumbing, with no sockets or network access."""

from unittest.mock import Mock

import pytest

from game_tester.game_bot import GameBot
from game_tester.login import login_client, login_session
from pyreborn import Client
from pyreborn.protocol import Protocol


@pytest.mark.parametrize('host,source,destination', [
    ('localhost', None, 'localhost'),
    ('localhost', '127.0.0.2', '127.0.0.1'),
    ('LOCALHOST', '127.0.0.2', '127.0.0.1'),
    ('127.0.0.1', '127.0.0.2', '127.0.0.1'),
    ('server.example', '192.0.2.2', 'server.example'),
    ('localhost', '::1', 'localhost'),
    ('::1', None, '::1'),
])
def test_native_connect_binds_requested_source(monkeypatch, host, source, destination):
    connection = Mock()
    create = Mock(return_value=connection)
    monkeypatch.setattr('pyreborn.protocol.socket.create_connection', create)
    protocol = Protocol(host, 14900, source_address=source)
    assert protocol.connect()
    create.assert_called_once_with(
        (destination, 14900), timeout=30.0,
        source_address=None if source is None else (source, 0))
    connection.setblocking.assert_called_once_with(False)
    assert protocol.host == host


@pytest.mark.parametrize('source', [None, '127.0.0.2'])
def test_client_and_bot_forward_source(source):
    assert Client(source_address=source)._protocol.source_address == source
    assert GameBot('qa', source_address=source).client._protocol.source_address == source


def test_login_client_binds_before_connect_and_preserves_existing_bind(monkeypatch):
    client = Client(source_address='127.0.0.1')
    observed = []
    monkeypatch.setattr(client, 'connect',
                        lambda: observed.append(client._protocol.source_address) or False)
    login_client(client, 'qa', 'pw', source_address='127.0.0.2')
    login_client(client, 'qa', 'pw')
    assert observed == ['127.0.0.2', '127.0.0.2']


def test_login_session_passes_source_to_client_and_disconnects(monkeypatch):
    create = Mock(side_effect=OSError('offline'))
    monkeypatch.setattr('pyreborn.protocol.socket.create_connection', create)
    with login_session('localhost', 14900, 'qa', 'pw',
                       source_address='127.0.0.2') as outcome:
        assert not outcome.connected
        client = outcome.client
        assert client._protocol.source_address == '127.0.0.2'
    assert client._protocol.socket is None
    create.assert_called_once_with(('127.0.0.1', 14900), timeout=30.0,
                                   source_address=('127.0.0.2', 0))
