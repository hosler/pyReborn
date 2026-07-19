import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..', 'pygserver'))

from pygserver.protocol.packets import build_npc_showimgs
from pyreborn.client import Client, HANDLED_PLO_IDS
from pyreborn.packets import PacketID, parse_npc_showimgs


def _body(packet):
    return packet[1:-1]


def test_npc_showimg_create_change_and_clear():
    npc_id = 123
    initial = build_npc_showimgs(npc_id, {
        7: {0: 'lamp.png', 1: 25, 2: 41, 3: 1, 5: (200, 100, 50, 160), 6: 15}
    })
    parsed = parse_npc_showimgs(_body(initial))
    assert parsed['npc_id'] == npc_id
    assert parsed['records'][7]['image'] == 'lamp.png'
    assert parsed['records'][7]['x'] == 12.5
    assert parsed['records'][7]['y'] == 20.5

    client = Client('localhost', 14900)
    client.npcs[npc_id] = {'x': 1, 'y': 2}
    client._handle_packet(PacketID.PLO_SHOWIMGNPC, _body(initial))
    layer = client.npcs[npc_id]['imgs'][7]
    assert layer['image'] == 'lamp.png'
    assert layer['colors'] == (1.0, 0.5, 0.25, 0.8)
    assert layer['zoom'] == 1.5

    change = build_npc_showimgs(npc_id, {7: {1: 30, 3: 4}})
    client._handle_packet(PacketID.PLO_SHOWIMGNPC, _body(change))
    assert layer['x'] == 15.0
    assert layer['y'] == 20.5
    assert layer['vis'] == 4

    clear = build_npc_showimgs(npc_id, {}, reset=True)
    client._handle_packet(PacketID.PLO_SHOWIMGNPC, _body(clear))
    assert client.npcs[npc_id]['imgs'] == {}
    assert PacketID.PLO_SHOWIMGNPC in HANDLED_PLO_IDS
