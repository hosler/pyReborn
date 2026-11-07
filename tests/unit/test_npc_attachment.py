"""Attachment packets, lifecycle and shared local/remote presentation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from reborn_protocol.props import PLAYER_PROPS, encode_value

from pyreborn.attachments import attach, detach, sync_attachment, update_attachments
from pyreborn.game.frame_context import FrameContext
from pyreborn.game.render_collect import EntityCollectMixin
from pyreborn.gs2_client import ClientGS2
from pyreborn.handlers.entities import (
    handle_npc_del, handle_npc_del2, handle_npc_props, handle_other_player_props,
    handle_player_props,
)
from reborn_protocol.props import NPC_PROPS
from .test_putnpc_family import _attach_setup, _fake_connected_client


def prop_stream(*values):
    return b''.join(bytes([pid + 32]) + encode_value(PLAYER_PROPS[pid], value)
                    for pid, value in values)


def remote(client, *values):
    # GSHORT player id 7.
    handle_other_player_props(client, b' '+bytes([39])+prop_stream(*values))
    return client.players.get(7)


@pytest.fixture
def client():
    client = _fake_connected_client()
    client._use_pixel_props = True
    client._current_level_name = 'room.nw'
    client.npcs[9] = {'x': 10, 'y': 20, 'z': 3, '_level': 'room.nw'}
    return client


def test_remote_follows_parent_and_relative_partial_updates(client):
    player = remote(client, (78, 12), (79, 21))
    remote(client, (42, (0, 9)), (78, -1.25), (79, .625))
    assert (player['x'], player['y']) == (8.75, 20.625)
    client.npcs[9].update(x=13, y=24)
    update_attachments(client)
    assert (player['x'], player['y']) == (11.75, 24.625)
    remote(client, (79, -2.5))
    assert (player['x'], player['y']) == (11.75, 21.5)
    remote(client, (42, (1, 0)))
    client.npcs[9].update(x=30, y=30)
    update_attachments(client)
    assert '_attachment' not in player
    assert (player['x'], player['y']) == (11.75, 21.5)


@pytest.mark.parametrize('local', [False, True])
def test_carrynpc_with_axes_keeps_absolute_position_without_attachment(client, local):
    values = ((24, 9), (78, 8.75), (79, 21.625))
    client._protocol.sent.clear()
    if local:
        handle_player_props(client, prop_stream(*values))
        player = vars(client.player)
    else:
        player = remote(client, *values)
    assert player['carry_npc'] == 9
    assert '_attachment' not in player
    assert (player['x'], player['y']) == (8.75, 21.625)
    client.npcs[9].update(x=30, y=40)
    update_attachments(client)
    assert (player['x'], player['y']) == (8.75, 21.625)
    assert not client._protocol.sent


@pytest.mark.parametrize('local', [False, True])
def test_deferred_attachment_resolves_when_npc_packet_arrives(client, local):
    payload = prop_stream((42, (0, 19)), (78, -1.5), (79, 2.25))
    if local:
        handle_player_props(client, payload)
        player = vars(client.player)
    else:
        player = remote(client, (42, (0, 19)), (78, -1.5), (79, 2.25))
    assert player['_attachment']['pending']
    handle_npc_props(client, b'  3' + b''.join(bytes([pid + 32]) + encode_value(NPC_PROPS[pid], value)
                                      for pid, value in ((75, 30), (76, 40))))
    assert (player['x'], player['y']) == (28.5, 42.25)
    assert not player['_attachment'].get('pending')


@pytest.mark.parametrize('local', [False, True])
@pytest.mark.parametrize('explicit_level', [False, True])
def test_npc_deletion_detaches_without_reattaching_reused_id(client, local, explicit_level):
    if local:
        client.player.x, client.player.y = 12, 21
        player = client.player
        attach(client, player, 9)
    else:
        player = remote(client, (42, (0, 9)), (78, 2), (79, 1))
    if explicit_level:
        handle_npc_del2(client, bytes([len('room.nw') + 32]) + b'room.nw  ' + bytes([41]))
    else:
        handle_npc_del(client, b'  ' + bytes([41]))
    assert 9 not in client.npcs
    data = player if isinstance(player, dict) else vars(player)
    assert '_attachment' not in data
    client.npcs[9] = {'x': 50, 'y': 50}
    update_attachments(client)
    assert (data['x'], data['y']) == (12, 21)


def test_pending_zero_and_level_reset_clear_links(client):
    player = remote(client, (42, (0, 19)), (78, 1), (79, 2))
    remote(client, (42, (0, 0)))
    assert '_attachment' not in player
    remote(client, (42, (0, 9)), (78, 1), (79, 2))
    attach(client, client.player, 9)
    client._reset_level_state()
    assert '_attachment' not in player
    assert client.player.attached_npc_id == 0


def test_local_wire_uses_attachnpc_then_relative_stored_axes():
    client, gs1 = _attach_setup(player_x=12.03, player_y=6.04)
    assert (client.player.x, client.player.y) == (12, 6.0625)
    packet_id, payload = client._protocol.sent[-1]
    assert payload == prop_stream((42, (0, 9)), (78, 2), (79, 1.0625))
    client.npcs[9]['x'] = 11
    gs1.process_attachment()
    assert client.player.x == 13
    detach(client, client.player, send=True)
    assert client._protocol.sent[-1][1] == prop_stream((42, (0, 0)), (78, 13), (79, 6.0625))


def test_gs2_attach_commands_and_live_members(client):
    rt = ClientGS2(client)
    rt.vms.setdefault('npc', {})[9] = SimpleNamespace(this=object())
    rt._executing_vm = SimpleNamespace(_gs2_owner=('npc', 9))
    client.player.x, client.player.y = 12, 21
    rt.host.call_builtin(None, 'attachplayertoobj', [0, 9], None)
    assert rt.player_object.get('attached') == 1
    assert rt.player_object.get('attachid') == 9
    assert rt.player_object.get('attachedtoobject') is rt.vms['npc'][9].this
    rt._executing_vm = None
    assert rt.player_object.get('attached') == 0
    rt.host.call_builtin(None, 'detachplayer', [], None)
    assert rt.player_object.get('attachid') == 0


def test_draw_uses_parent_interpolation_z_and_ground_depth(client):
    player = remote(client, (42, (0, 9)), (78, 2), (79, 1))
    game = EntityCollectMixin()
    game.client = client
    game.camera = SimpleNamespace(world_to_screen=lambda x, y: (x * 16, y * 16))
    game.npc_visual = {9: (8, 18)}
    game._npc_visual_epoch = {9: None}
    game.other_player_visual = {7: (0, 0)}
    game.lerp_speed = 10
    game._entity_on_screen = Mock(return_value=True)
    frame = FrameContext(dt=.05, screen_size=(800, 600))
    out = []
    game._collect_other_players(out, frame)
    entity = out[0]
    assert (entity.x, entity.y) == (11 * 16, 17 * 16)
    assert entity.depth == 23
    assert entity.z == 3
    assert game._interpolate_npc(9, client.npcs[9], 10, 20, frame) == (9, 19)
    assert player['y'] == 21


def test_existing_attachment_ignores_unknown_and_unsupported_targets(client):
    client.player.x, client.player.y = 12, 21
    attach(client, client.player, 9)
    handle_player_props(client, prop_stream((42, (0, 19))))
    handle_player_props(client, prop_stream((42, (1, 9))))
    assert client.player.attached_npc_id == 9
    assert sync_attachment(client, client.player) is client.npcs[9]


def test_attached_walk_rounds_offset_and_sends_signed_relative_position(client):
    client.player.x, client.player.y = 8.75, 19.375
    attach(client, client.player, 9)
    client.player.x = 8.73
    assert client.player.x == 8.75
    client.send_position()
    from pyreborn.packet_codec.common import parse_player_props
    props = parse_player_props(client._protocol.sent[-1][1])
    assert (props['x'], props['y']) == (-1.25, -.625)
    client.move(1, 0, step=.23)
    props = parse_player_props(client._protocol.sent[-1][1])
    assert (props['x'], props['y']) == (-1, -.625)
    assert (client.player.x, client.player.y) == (9, 19.375)


def test_gmap_attachment_uses_npc_world_position_and_keeps_signed_wire_axes(client):
    client.gmap_grid = {(1, 1): 'room.nw'}
    client.npcs[9].update(world_x=74, world_y=84)
    client.player.x, client.player.y = 73, 85
    attach(client, client.player, 9, send=True)
    assert client._protocol.sent[-1][1] == prop_stream((42, (0, 9)), (78, -1), (79, 1))
    player = remote(client, (42, (0, 9)), (78, -2), (79, 1))
    assert (player['x'], player['y']) == (72, 85)
    client.npcs[9].update(world_x=76, world_y=87, x=12, y=23)
    update_attachments(client)
    assert (player['x'], player['y']) == (74, 88)
    assert (client.player.x, client.player.y) == (75, 88)
    client.send_position()
    assert client._protocol.sent[-1][1] == prop_stream((17, client.player.direction), (78, -1), (79, 1))


def test_deferred_local_gmap_position_sends_offsets_without_segment_subtraction(client):
    client.gmap_grid = {(1, 1): 'room.nw'}
    handle_player_props(client, prop_stream((42, (0, 19)), (78, -1.5), (79, 2.25)))
    client.send_position()
    assert client._protocol.sent[-1][1] == prop_stream(
        (17, client.player.direction), (78, -1.5), (79, 2.25))


def test_local_draw_uses_same_parent_position_and_inherited_z(client):
    client.player.x, client.player.y = 12, 21
    attach(client, client.player, 9)
    game = EntityCollectMixin()
    game.client = client
    game.camera = SimpleNamespace(world_to_screen=lambda x, y: (x * 16, y * 16))
    game.npc_visual = {}
    game.visual_y = 5
    out = []
    game._collect_local_player(out, FrameContext())
    assert (out[0].x, out[0].y, out[0].depth, out[0].z) == (192, 288, 24, 3)


def test_classic_server_keeps_attachment_local_and_sends_level_axes(client):
    # Pre-2.30 servers know neither ATTACHNPC (42) nor X2/Y2.
    client._use_pixel_props = False
    client.player.x, client.player.y = 8.75, 19.375
    sent = len(client._protocol.sent)
    attach(client, client.player, 9, send=True)
    assert len(client._protocol.sent) == sent
    client.send_position()
    # Classic X/Y (15/16) carry absolute level-local half-tiles, not offsets.
    assert client._protocol.sent[-1][1] == b'1' + bytes([client.player.direction + 32]) \
        + bytes([15 + 32, int(8.75 * 2 + .5) + 32, 16 + 32, int(19.375 * 2 + .5) + 32])
