"""Call order and arguments of the callbacks that used to be forwarded by hand.

Written before the multi-subscriber mechanism replaced the forwarding: each case
records who runs, in which order and with what, with stub subscribers on a real
Client. They must stay green across that refactor.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyreborn.client import Client
from pyreborn.game.callbacks import client_callbacks
from pyreborn.game.callbacks.client_callbacks import Gs2SourceRouter
from pyreborn.game.level_arrival import LevelArrival
from pyreborn.gs2_client import ClientGS2
from pyreborn.packets import PacketID


def _client():
    client = Client('localhost', 14900)
    client._authenticated = True
    client._protocol = SimpleNamespace(connected=True,
                                       send_packet=Mock(return_value=True))
    return client


class _RecordingAttempts(dict):
    def __init__(self, log):
        super().__init__()
        self._log = log

    def pop(self, key, *default):
        self._log.append(('game', 'forget', key))
        return super().pop(key, *default)


def _stub_game(client, log):
    game = SimpleNamespace(
        client=client, gs1=Mock(scripts={}), sound_mgr=SimpleNamespace(),
        _request_asset=Mock(), arrival=LevelArrival(gs1_level='test.nw'), npc_handler=Mock(),
        _append_chat=lambda text: log.append(('game', 'chat', text)))
    game.gs2_sources = Gs2SourceRouter()
    game.gs2_sources.attempts = _RecordingAttempts(log)
    return game


def _attach_gs2(client, log):
    runtime = ClientGS2(client)
    runtime.handle_server_text = lambda text: log.append(('gs2', 'text', text))
    runtime.attach()
    runtime.pump_pending = lambda: log.append(
        ('gs2', 'bytecode', runtime._pending_bytecode[-1]))
    return runtime


def test_server_text_game_chat_runs_before_gs2_exactly_once():
    log = []
    client = _client()
    game = _stub_game(client, log)
    game.gs2 = _attach_gs2(client, log)
    client_callbacks.wire_client_callbacks(game)
    client._handle_packet(PacketID.PLO_SERVERTEXT, b'hello there')
    assert log == [('game', 'chat', '[server] hello there'),
                   ('gs2', 'text', 'hello there')]


def test_server_text_headless_reaches_gs2_alone():
    log = []
    client = _client()
    _attach_gs2(client, log)
    client._handle_packet(PacketID.PLO_SERVERTEXT, b'hello there')
    assert log == [('gs2', 'text', 'hello there')]


def test_bytecode_embedder_slot_runs_before_gs2():
    log = []
    client = _client()
    client.on_gs2_bytecode = lambda kind, key, blob: log.append(
        ('slot', kind, key, blob))
    _attach_gs2(client, log)
    client._handle_packet(131, b' )r\xde\xad\xbe')
    assert log == [('slot', 'npc', 1234, b'\xde\xad\xbe'),
                   ('gs2', 'bytecode', ('npc', 1234, b'\xde\xad\xbe'))]


def test_weapon_delete_game_hook_runs_before_the_embedder_hook():
    log = []
    client = _client()
    client.on_packet[PacketID.PLO_NPCWEAPONDEL] = (
        lambda data: log.append(('embedder', data)))
    game = _stub_game(client, log)
    client_callbacks.wire_client_callbacks(game)
    client._handle_packet(PacketID.PLO_NPCWEAPONDEL, b'sword')
    assert log == [('game', 'forget', ('weapon', 'sword')),
                   ('embedder', b'sword')]


# -- the mechanism ----------------------------------------------------------

from pyreborn.client_callbacks import emit
from pyreborn.nc_client import NCClient
from pyreborn.rc_client import RCClient


def test_slot_assignment_still_works_and_runs_before_listeners():
    client = _client()
    seen = []
    client.add_listener('on_chat', lambda pid, msg: seen.append(('listener', pid, msg)))
    client.on_chat = lambda pid, msg: seen.append(('slot', pid, msg))
    assert client.on_chat is not None
    client.emit('on_chat', 3, 'hi')
    assert seen == [('slot', 3, 'hi'), ('listener', 3, 'hi')]
    client.on_chat = None
    seen.clear()
    client.emit('on_chat', 4, 'yo')
    assert seen == [('listener', 4, 'yo')]


def test_listeners_run_in_registration_order_and_remover_is_idempotent():
    client = _client()
    seen = []
    remove_a = client.add_listener('on_flag', lambda n, v: seen.append('a'))
    client.add_listener('on_flag', lambda n, v: seen.append('b'))
    remove_a()
    remove_a()
    client.emit('on_flag', 'x', 'y')
    assert seen == ['b']


def test_unknown_callback_name_is_rejected():
    client = _client()
    with pytest.raises(ValueError):
        client.add_listener('on_not_a_callback', lambda: None)
    with pytest.raises(ValueError):
        client.add_listener('on_packet', lambda: None)


def test_emit_returns_the_slots_value_and_passes_keywords():
    client = _client()
    client.on_hurt = lambda *a, **k: ('slot', a, k)
    client.add_listener('on_hurt', lambda *a, **k: 'ignored')
    assert client.emit('on_hurt', 1, name='n') == ('slot', (1,), {'name': 'n'})


def test_exceptions_propagate_and_stop_later_subscribers():
    client = _client()
    seen = []

    def boom(*_):
        raise RuntimeError('boom')

    client.on_chat = boom
    client.add_listener('on_chat', lambda *a: seen.append('listener'))
    with pytest.raises(RuntimeError):
        client.emit('on_chat', 1, 'x')
    assert seen == []


def test_emit_tolerates_stand_in_clients():
    stand_in = SimpleNamespace(on_chat=Mock())
    emit(stand_in, 'on_chat', 1, 'x')
    stand_in.on_chat.assert_called_once_with(1, 'x')
    emit(SimpleNamespace(), 'on_chat', 1, 'x')


@pytest.mark.parametrize('cls', [RCClient, NCClient])
def test_staff_clients_have_the_mechanism(cls):
    client = cls('localhost', 14900)
    seen = []
    client.add_listener('on_file', lambda name, data: seen.append(name))
    client.emit('on_file', 'a.png', b'')
    assert seen == ['a.png']


def test_every_callback_slot_is_a_listener_target():
    names = Client.callback_names()
    assert 'on_packet' not in names and len(names) >= 58
    client = _client()
    assert all(getattr(client, name) is None for name in names)


def test_gs2_detach_unsubscribes():
    log = []
    client = _client()
    runtime = _attach_gs2(client, log)
    runtime.detach()
    client._handle_packet(PacketID.PLO_SERVERTEXT, b'hello')
    assert log == []


def test_gs2_attach_is_idempotent_and_detach_leaves_nothing():
    log = []
    client = _client()
    runtime = ClientGS2(client)
    runtime.handle_server_text = lambda text: log.append(text)
    runtime.attach()
    runtime.attach()
    client._handle_packet(PacketID.PLO_SERVERTEXT, b'hello there')
    assert log == ['hello there']
    runtime.detach()
    client._handle_packet(PacketID.PLO_SERVERTEXT, b'hello again')
    assert log == ['hello there']
    assert not any(client._listeners.values())
    runtime.attach()                      # attach after detach works again
    client._handle_packet(PacketID.PLO_SERVERTEXT, b'third')
    assert log == ['hello there', 'third']
