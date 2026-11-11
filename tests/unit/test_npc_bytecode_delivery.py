"""Level-NPC bytecode (PLO_NPCBYTECODE 131) from the wire to the GS2 runtime.

Byte vectors are the ones in the 2026-11-11 oracle notes, cited against
GServer-v2 origin/beta4: 131 is sent as raw data (server/src/player/Player.cpp
sendRawPacket; gs2lib wraps it as `[GCHAR 100][GINT3 len+1]['\\n']` + packet +
`'\\n'`) with packet = `[GCHAR 131][GINT3 npc_id][bytecode]`
(src/level/Level.cpp:1475-1480). Only modern servers send it, and then the
NPC's SCRIPT prop is `21 20 20` and CLASS (74) carries the joined-class list
(PropertySerializers.cpp:84-88, 554-555).
"""

import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyreborn import Client
from pyreborn.gs2_client import ClientGS2
from pyreborn.packet_codec.files import parse_npc_bytecode
from pyreborn.packets import PacketID, build_update_class, parse_npc_props
from pyreborn.protocol import Protocol, WebSocketProtocol
import pyreborn.protocol as protocol_module
from reborn_protocol.gs2 import Op

# id 1234, bytecode DE AD BE: RAWDATA header line, then the 8-byte raw packet
# (id byte + 3 id bytes + 3 bytecode bytes + newline).
VECTOR_131 = bytes.fromhex("84 20 20 28 0A  A3 20 29 72 DE AD BE 0A")
# Same NPC, modern props: empty SCRIPT, then CLASS "foo,bar".
VECTOR_CLASS_PROP = bytes.fromhex("6A 20 27 66 6F 6F 2C 62 61 72")


def _gint3(value):
    return bytes([(value >> 14) + 32, ((value >> 7) & 127) + 32,
                  (value & 127) + 32])


def _frame_131(npc_id, bytecode):
    raw = bytes([131 + 32]) + _gint3(npc_id) + bytecode + b'\n'
    return bytes([100 + 32]) + _gint3(len(raw)) + b'\n' + raw


def _bytecode():
    segments = [(1, b'\0' * 4), (2, b'\0' * 4 + b'onCreated\0'),
                (3, b'line\nname\0'), (4, bytes([Op.OP_RET]))]
    return b''.join(struct.pack('>II', kind, len(body)) + body
                    for kind, body in segments) + b'\n'


def _through_codec(decrypted, transport, monkeypatch):
    if transport == 'websocket':
        proto = WebSocketProtocol('ws://localhost', 'localhost', 14900)
        proto._parse_packets(decrypted)
        return list(proto.pending_packets)
    proto = Protocol('localhost', 14900)
    proto.connected = True
    proto.first_packet = False
    proto.codec.recv_packet = lambda data: data

    class Socket:
        chunk = b''

        def setblocking(self, flag):
            pass

        def recv(self, size):
            if not self.chunk:
                raise BlockingIOError
            data, self.chunk = self.chunk, b''
            return data

    proto.socket = Socket()
    monkeypatch.setattr(protocol_module.select, 'select',
                        lambda *args: ([proto.socket], [], []))
    proto.socket.chunk = struct.pack('>H', len(decrypted)) + decrypted
    packets = proto.recv_packets()
    assert proto.raw_data_expected == 0 and proto.raw_data_buffer == b''
    return packets


def _client():
    client = Client('localhost', 14900)
    client._authenticated = True
    client._protocol = SimpleNamespace(connected=True,
                                       send_packet=Mock(return_value=True))
    client.on_gs2_bytecode = Mock()
    return client, ClientGS2(client).attach()


def test_hand_framer_reproduces_the_oracle_vector():
    assert _frame_131(1234, b'\xde\xad\xbe') == VECTOR_131


@pytest.mark.parametrize('transport', ['native', 'websocket'])
def test_plo131_vector_unwraps_to_id_and_bytecode(transport, monkeypatch):
    packets = _through_codec(VECTOR_131, transport, monkeypatch)
    assert packets == [(100, b'  ('), (131, b' )r\xde\xad\xbe')]
    assert parse_npc_bytecode(packets[1][1]) == {
        'npc_id': 1234, 'bytecode': b'\xde\xad\xbe'}


@pytest.mark.parametrize('transport', ['native', 'websocket'])
def test_plo131_vector_reaches_the_gs2_runtime_for_that_npc(
        transport, monkeypatch):
    client, runtime = _client()
    loaded = []
    monkeypatch.setattr(
        runtime, 'load_bytecode',
        lambda kind, key, blob: loaded.append((kind, key, blob)))

    for packet_id, body in _through_codec(VECTOR_131, transport, monkeypatch):
        client._handle_packet(packet_id, body)

    assert loaded == [('npc', 1234, b'\xde\xad\xbe')]
    assert client.gs2_bytecode['npc'][1234] == b'\xde\xad\xbe'
    runtime._prev_bytecode_cb.assert_called_once_with(
        'npc', 1234, b'\xde\xad\xbe')


def test_plo131_real_bytecode_becomes_that_npcs_vm(monkeypatch):
    client, runtime = _client()
    blob = _bytecode()
    for packet_id, body in _through_codec(_frame_131(77, blob), 'native',
                                          monkeypatch):
        client._handle_packet(packet_id, body)
    assert client.gs2_bytecode['npc'][77] == blob
    assert runtime.vms['npc'][77].has_function('onCreated')
    assert 1234 not in runtime.vms['npc']


def test_empty_script_and_class_props_stay_aligned():
    """SCRIPT `21 20 20` (empty) then CLASS (74) then X2 (75): the CLASS
    payload is a GSHORT-length string, and the prop after it must still parse
    (no clean-stream failure, no lost X2)."""
    npc_id = _gint3(1234)
    x2 = bytes([0x6B, 0x21, 0x24])  # X2: GSHORT 132 -> 66 px -> 4.125 tiles
    data = (npc_id + bytes([0x20, 0x25]) + b'a.png'          # IMAGE
            + bytes.fromhex("21 20 20")                       # SCRIPT, empty
            + VECTOR_CLASS_PROP + x2)

    props = parse_npc_props(data)

    assert props['id'] == 1234
    assert props['image'] == 'a.png'
    assert props['script'] == ''
    assert props['x'] == pytest.approx(4.125)

    client = Client('localhost', 14900)
    client._handle_packet(PacketID.PLO_NPCPROPS, data)
    record = client.npcs[1234]
    assert record['script'] == '' and record['image'] == 'a.png'
    assert record['x'] == pytest.approx(4.125)


def test_class_prop_alone_consumes_exactly_its_bytes():
    data = _gint3(5) + VECTOR_CLASS_PROP
    assert parse_npc_props(data) == {'id': 5, 'classes': ['foo', 'bar']}


def _class_prop(text: bytes) -> bytes:
    return bytes([74 + 32, 32 + (len(text) >> 7),
                  32 + (len(text) & 127)]) + text


def test_class_list_is_cleaned_and_capped():
    props = parse_npc_props(_gint3(5) + _class_prop(
        b'good, a/b ,c\\d,bad\x01name,good,,' + b'x' * 129 + b',ok2'))
    assert props['classes'] == ['good', 'ok2']
    many = b','.join(b'c%d' % i for i in range(200))
    assert len(parse_npc_props(_gint3(5) + _class_prop(many))['classes']) == 64


def _class_requests(client):
    return [call.args[1] for call in client._protocol.send_packet.call_args_list
            if call.args[0] == PacketID.PLI_UPDATECLASS]


def test_class_prop_pulls_each_class_once_and_joins_the_npc(monkeypatch):
    client, runtime = _client()
    props = lambda npc_id: _gint3(npc_id) + VECTOR_CLASS_PROP  # noqa: E731

    client._handle_packet(PacketID.PLO_NPCPROPS, props(1234))
    assert client.npcs[1234]['classes'] == ['foo', 'bar']
    assert _class_requests(client) == [build_update_class('foo'),
                                       build_update_class('bar')]

    # a second NPC listing the same classes asks for nothing more
    client._handle_packet(PacketID.PLO_NPCPROPS, props(77))
    assert len(_class_requests(client)) == 2

    # props came first; the bytecode then the classes arrive later
    for packet_id, body in _through_codec(_frame_131(1234, _bytecode()),
                                          'native', monkeypatch):
        client._handle_packet(packet_id, body)
    vm = runtime.vms['npc'][1234]
    assert vm.joined == []
    assert runtime._pending_joins.keys() == {'foo', 'bar'}
    runtime.load_bytecode('class', 'foo', _bytecode())
    assert [j._gs2_key for j in vm.joined] == ['foo']
    assert len(_class_requests(client)) == 2


def test_class_prop_joins_an_already_loaded_vm_and_class(monkeypatch):
    client, runtime = _client()
    runtime.load_bytecode('class', 'foo', _bytecode())
    runtime.load_bytecode('npc', 5, _bytecode())
    client._handle_packet(PacketID.PLO_NPCPROPS, _gint3(5) + VECTOR_CLASS_PROP)
    assert [j._gs2_key for j in runtime.vms['npc'][5].joined] == ['foo']
    assert _class_requests(client) == [build_update_class('bar')]


# -- round 2: listed joins must not hang or outlive their NPC -----------------

def _props(npc_id, text):
    return _gint3(npc_id) + _class_prop(text)


def test_listed_join_for_a_class_that_never_arrives_expires():
    client, runtime = _client()
    runtime.load_bytecode('npc', 1, _bytecode())
    client._handle_packet(PacketID.PLO_NPCPROPS, _props(1, b'ghostclass'))
    vm = runtime.vms['npc'][1]
    assert runtime._has_pending_joins(vm)
    runtime.trigger_npc_event(1, 'onCreated')          # queued behind the join
    assert runtime._join_gated_events

    runtime.process_timeouts(0.0)
    assert runtime._has_pending_joins(vm)              # deadline not reached
    for key, (owner, _) in list(runtime._listed_join_deadlines.items()):
        runtime._listed_join_deadlines[key] = (owner, 0.0)
    runtime.process_timeouts(0.0)

    assert not runtime._has_pending_joins(vm)
    assert runtime._join_gated_events == {}
    assert runtime._listed_join_deadlines == {}


def test_listed_class_past_the_request_cap_is_not_left_pending(monkeypatch):
    client, runtime = _client()
    monkeypatch.setattr(type(runtime), 'MAX_PULLED_CLASSES', 2)
    runtime.load_bytecode('npc', 1, _bytecode())
    client._handle_packet(PacketID.PLO_NPCPROPS, _props(1, b'a,b,c,d'))
    vm = runtime.vms['npc'][1]
    assert len(_class_requests(client)) == 2
    assert set(runtime._pending_joins) == {'a', 'b'}   # c, d never requested
    runtime.load_bytecode('class', 'a', _bytecode())
    runtime.load_bytecode('class', 'b', _bytecode())
    assert not runtime._has_pending_joins(vm)


def test_forget_npc_drops_pending_joins_and_gated_events():
    client, runtime = _client()
    runtime.load_bytecode('npc', 1, _bytecode())
    client._handle_packet(PacketID.PLO_NPCPROPS, _props(1, b'late'))
    dead = runtime.vms['npc'][1]
    runtime.trigger_npc_event(1, 'onCreated')
    assert runtime._join_gated_events

    runtime.forget_npc(1)

    assert runtime._pending_joins == {}
    assert runtime._join_gated_events == {}
    assert runtime._listed_join_deadlines == {}
    runtime.load_bytecode('class', 'late', _bytecode())   # late arrival
    assert dead.joined == []
    runtime.load_bytecode('npc', 1, _bytecode())           # reused id
    assert not runtime._has_pending_joins(runtime.vms['npc'][1])


def test_empty_class_prop_clears_the_stored_list():
    client, runtime = _client()
    client._handle_packet(PacketID.PLO_NPCPROPS, _props(5, b'old'))
    assert runtime._npc_class_lists[5] == ['old']
    client._handle_packet(PacketID.PLO_NPCPROPS, _props(5, b''))
    assert client.npcs[5]['classes'] == []
    assert 5 not in runtime._npc_class_lists
    runtime.load_bytecode('npc', 5, _bytecode())
    assert not runtime._has_pending_joins(runtime.vms['npc'][5])
    # an absent CLASS prop changes nothing
    client._handle_packet(PacketID.PLO_NPCPROPS, _props(6, b'keep'))
    client._handle_packet(PacketID.PLO_NPCPROPS, _gint3(6) + b'\x20\x25a.png')
    assert runtime._npc_class_lists[6] == ['keep']


def _expire_all(runtime):
    for key, (owner, _) in list(runtime._listed_join_deadlines.items()):
        runtime._listed_join_deadlines[key] = (owner, 0.0)
    runtime.process_timeouts(0.0)


def test_class_arriving_after_expiry_is_still_joined_exactly_once():
    client, runtime = _client()
    runtime.load_bytecode('npc', 1, _bytecode())
    client._handle_packet(PacketID.PLO_NPCPROPS, _props(1, b'slow'))
    vm = runtime.vms['npc'][1]
    _expire_all(runtime)
    assert not runtime._has_pending_joins(vm) and vm.joined == []

    runtime.load_bytecode('class', 'slow', _bytecode())
    assert [j._gs2_key for j in vm.joined] == ['slow']
    runtime.load_bytecode('class', 'slow', _bytecode())    # re-sent: no dup
    assert [j._gs2_key for j in vm.joined] == ['slow']


def test_class_arriving_late_skips_a_forgotten_npc():
    client, runtime = _client()
    runtime.load_bytecode('npc', 1, _bytecode())
    client._handle_packet(PacketID.PLO_NPCPROPS, _props(1, b'slow'))
    dead = runtime.vms['npc'][1]
    _expire_all(runtime)
    runtime.forget_npc(1)
    runtime.load_bytecode('class', 'slow', _bytecode())
    assert dead.joined == [] and 1 not in runtime.vms['npc']


def _del2(level: bytes, npc_id: int) -> bytes:
    return bytes([32 + len(level)]) + level + _gint3(npc_id)


@pytest.mark.parametrize('delete', ['del', 'del2'])
def test_deleted_npc_bytecode_blob_is_dropped_and_id_can_be_reused(
        delete, monkeypatch):
    """pygserver sends NPC-delete-2 before props when an NPC goes from
    bytecode to a text script; the stored blob must not be replayed into a
    host installed afterwards, and a fresh 131 for the id still works."""
    client = Client('localhost', 14900)
    blob = _bytecode()
    client.gs2_bytecode['class']['keep'] = blob
    client.gs2_bytecode['weapon']['keepw'] = blob
    for packet_id, body in _through_codec(_frame_131(77, blob), 'native',
                                          monkeypatch):
        client._handle_packet(packet_id, body)
    assert client.gs2_bytecode['npc'][77] == blob

    if delete == 'del':
        client._handle_packet(PacketID.PLO_NPCDEL, _gint3(77))
    else:
        client._handle_packet(PacketID.PLO_NPCDEL2, _del2(b'a.nw', 77))
    script = b'//#CLIENTSIDE\n'
    text_props = _gint3(77) + bytes([21 + 32, 32 + len(script)]) + script
    client._handle_packet(PacketID.PLO_NPCPROPS, text_props)

    assert 77 not in client.gs2_bytecode['npc']
    assert client.gs2_bytecode['class']['keep'] == blob      # untouched
    assert client.gs2_bytecode['weapon']['keepw'] == blob
    for _ in range(2):                    # install, then reinstall
        runtime = ClientGS2(client).attach()
        assert 77 not in runtime.vms['npc']

    for packet_id, body in _through_codec(_frame_131(77, blob), 'native',
                                          monkeypatch):
        client._handle_packet(packet_id, body)
    assert client.gs2_bytecode['npc'][77] == blob
    assert ClientGS2(client).attach().vms['npc'][77].has_function('onCreated')
