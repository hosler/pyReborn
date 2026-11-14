"""Server packet behaviour checked against the reference client."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
import pytest

from pyreborn.client import Client
from pyreborn.game.frame_context import FrameContext
from pyreborn.game.render_entities import EntityRenderMixin
from pyreborn.game.render_gani import GaniRenderMixin
from pyreborn.npc_movement import tick_moves
from pyreborn.pygame_game import GameClient


def number(value, width=1):
    if width == 1:
        return bytes([32 + value])
    return bytes(32 + ((value >> shift) & 127)
                 for shift in range((width - 1) * 7, -1, -7))


def text(value):
    value = value.encode('latin-1')
    return number(len(value)) + value


def pixel(value):
    raw = round(abs(value) * 16) * 2 + (value < 0)
    return number(raw, 2)


def move_record(version, x, y, dx, dy, ticks, options):
    if version == '2.22':
        coords = b''.join(number(round(v)) for v in
                          (x * 2, y * 2, dx * 2 + 100, dy * 2 + 100))
    else:
        coords = b''.join(pixel(v) for v in (x, y, dx, dy))
    return coords + number(ticks, 2) + number(options)


@pytest.fixture(params=['2.22', '6.037'])
def client(request):
    result = Client('127.0.0.1', 14900, version=request.param)
    result.player.level = result._current_level_name = 'a.nw'
    result._level_scope = 'a.nw'
    result.test_version = request.param
    return result


@pytest.fixture
def game(client):
    pygame.init()
    pygame.display.set_mode((64, 64))
    return GameClient(client)


def test_player_images_are_layers_and_never_chat(game, client, monkeypatch):
    client.players[7] = {'x': 2, 'y': 3, 'level': 'a.nw'}
    chat = client.on_chat = Mock()
    wire = (number(7, 2) + number(17) + number(0) + text('lamp.png')
            + number(1) + number(5) + number(2) + number(9)
            + number(3) + number(1))
    client._handle_packet(32, wire)
    layer = client.players[7]['imgs'][7]
    assert (layer['image'], layer['x'], layer['y'], layer['vis']) == ('lamp.png', 2.5, 4.5, 1)
    chat.assert_not_called()
    seen = []
    monkeypatch.setattr(game, '_layer_place_for_sort', lambda rec, size: (6, 40, 72))
    game._collect_showimg_layers(seen, FrameContext(screen_size=(320, 240)))
    assert [ent.data for ent in seen] == [layer]
    client._handle_packet(32, number(7, 2) + number(17) + number(1) + number(8))
    assert layer['x'] == 4 and layer['y'] == 4.5
    client._handle_packet(32, number(7, 2) + number(17) + number(0) + number(0))
    assert client.players[7]['imgs'] == {}
    client._handle_packet(32, wire)
    client._handle_packet(32, number(7, 2) + number(9))
    assert client.players[7]['imgs'] == {}
    chat.assert_not_called()


def test_player_image_gui_pass(game, client, monkeypatch):
    client.players[7] = {'level': 'a.nw'}
    client._handle_packet(32, number(7, 2) + number(10) + number(0) + text('gui.png')
                          + number(3) + number(5))
    draw = Mock()
    monkeypatch.setattr(game, '_render_npc_layers', draw)
    game._render_gui_layers_inner()
    draw.assert_called_once_with(client.players[7]['imgs'], over=True, gui=True)


def test_move_all_records_run_for_their_duration_in_world_space(sim_time, client, monkeypatch):
    sim_time(lambda: 100.0)
    client.gmap_grid = {(-1, 2): 'a.nw'}
    client.npcs[7] = {'x': 2, 'y': 3, '_level': 'a.nw'}
    version = client.test_version
    packet = 165 if version == '2.22' else 189
    wire = (number(7, 3) + move_record(version, 2, 3, 2, -1, 4, 2)
            + move_record(version, 4, 2, -1, 2, 2, 2))
    client._handle_packet(packet, wire)
    assert len(client.npc_moves[7]['records']) == 2
    npc = client.npcs[7]
    assert (npc['world_x'], npc['world_y']) == (-62, 131)
    tick_moves(client, 100.1)
    assert (npc['x'], npc['y']) == pytest.approx((3, 2.5))
    tick_moves(client, 100.2)
    assert (npc['x'], npc['y']) == pytest.approx((4, 2))
    tick_moves(client, 100.3)
    assert (npc['x'], npc['y'], npc['world_x'], npc['world_y']) == pytest.approx((3, 4, -61, 132))
    assert not npc['_move_queue']


@pytest.mark.parametrize('options,far,compressed', [(0, False, False), (0, True, True),
                                                   (1, True, False), (2, False, False)])
def test_move_cache_and_absolute_modes(sim_time, client, monkeypatch, options, far, compressed):
    # FourPlay/quattroplay/src/TServerNPC.cpp addNPCMove: a zero options byte
    # appends relative to the queued deltas and, when the whole queue now
    # spans more than ten tiles, squeezes every pending duration; any non-zero
    # byte keeps the wire position and never rescales.
    sim_time(lambda: 10.0)
    client.npcs[7] = {'x': 2, 'y': 3}
    version = client.test_version
    packet = 165 if version == '2.22' else 189
    first_dx = 20 if far else 1
    client._handle_packet(packet, number(7, 3) + move_record(version, 2, 3, first_dx, 0, 20, 2))
    client._handle_packet(packet, number(7, 3) + move_record(version, 40, 40, 1, 0, 20, options))
    queue = client.npcs[7]['_move_queue']
    assert len(queue) == 2
    assert queue[0]['remaining'] == (.5 if compressed else 1)
    assert queue[1]['remaining'] == (.5 if compressed else 1)
    if options:
        assert (queue[1]['x'], queue[1]['y']) == (40, 40)
    else:
        assert (queue[1]['x'], queue[1]['y']) == (2 + first_dx, 3)


def test_relative_move_ignores_wire_position_but_absolute_keeps_it(client):
    version = client.test_version
    packet = 165 if version == '2.22' else 189
    client.npcs[7] = {'x': 1, 'y': 1}
    client._handle_packet(packet, number(7, 3) + move_record(version, 5, 6, 0, 0, 10, 0))
    assert (client.npcs[7]['x'], client.npcs[7]['y']) == (1, 1)
    client.npcs[8] = {'x': 1, 'y': 1}
    client._handle_packet(packet, number(8, 3) + move_record(version, 5, 6, 0, 0, 10, 1))
    assert (client.npcs[8]['x'], client.npcs[8]['y']) == (5, 6)


@pytest.mark.parametrize('options', [16, 20])
def test_move_options_are_not_client_flags(sim_time, client, monkeypatch, options):
    # The reference client queues server moves with a fixed flag value: the
    # apply-direction and block-check bits of the wire byte only mean
    # something to the server, which relays the resulting sprite and
    # position props itself.
    sim_time(lambda: 20.0)
    wall = Mock(return_value=True)
    client.gs1_host = SimpleNamespace(rt=SimpleNamespace(is_wall=wall))
    client.npcs[7] = {'x': 2, 'y': 3, 'image': '#c#', 'direction': 2}
    version = client.test_version
    client._handle_packet(165 if version == '2.22' else 189,
                          number(7, 3) + move_record(version, 2, 3, 2, 0, 4, options))
    tick_moves(client, 20.05)
    npc = client.npcs[7]
    assert npc['x'] == 2.5 and npc['direction'] == 2
    wall.assert_not_called()


def test_npc_moved_relocates_and_removes_from_level(client):
    client.gmap_grid = {(-1, 2): 'b.nw'}
    client.npcs[7] = {'x': 1, 'y': 1, '_level': 'a.nw', '_move_queue': [{}]}
    seen = client.on_npc_moved = Mock()
    client._handle_packet(24, number(7, 3) + number(5) + number(9) + b'b.nw')
    npc = client.npcs[7]
    assert (npc['_level'], npc['x'], npc['y']) == ('b.nw', 2.5, 4.5)
    assert (npc['world_x'], npc['world_y']) == (-61.5, 132.5)
    assert npc['visible'] and '_move_queue' not in npc
    seen.assert_called_once()
    client._handle_packet(24, number(7, 3))
    assert npc['_level'] == '' and not npc['visible']


@pytest.mark.parametrize('flags,visible,band', [(0, False, 1), (1, True, 1),
                                               (3, True, 2), (5, True, 0), (7, True, 0)])
def test_npc_visibility_and_draw_order(game, client, monkeypatch, flags, visible, band):
    client._handle_packet(3, number(7, 3) + number(0) + text('sign.png')
                          + number(2) + number(4) + number(3) + number(6)
                          + number(13) + number(flags))
    npc = client.npcs[7]
    assert npc['visible'] is visible
    monkeypatch.setattr(game, '_entity_on_screen', lambda *args, **kw: True)
    out = []
    game._collect_npcs(out, FrameContext(screen_size=(320, 240)))
    assert out[0].band == band
    loader = Mock(return_value=pygame.Surface((16, 16)))
    monkeypatch.setattr(game.sprite_mgr, 'load_sheet', loader)
    game._render_npc(32, 48, npc, 7)
    assert loader.called is visible
    client._handle_packet(3, number(7, 3) + number(13) + number(1))
    assert npc['visible'] and npc['draw_layer'] is None


def test_npc_equipment_and_attributes_reach_gani(game, client, monkeypatch):
    wire = (number(7, 3) + number(0) + text('#c#')
            + number(10) + number(33) + text('blade.png')
            + number(11) + number(12) + text('guard.png')
            + number(12) + text('idle')
            + number(36) + text('hat.png') + number(44) + text('cape.png')
            + number(73) + text('last.png'))
    client._handle_packet(3, wire)
    npc = client.npcs[7]
    assert (npc['sword_power'], npc['shield_power']) == (3, 2)
    anim = SimpleNamespace(set_animation=Mock(), gani=SimpleNamespace(is_movie=False))
    game.npc_anims[7] = anim
    draw = Mock()
    monkeypatch.setattr(game, '_render_animated_entity', draw)
    game._render_npc(10, 20, npc, 7)
    equip = draw.call_args.args[3]
    assert (equip['sword_image'], equip['shield_image']) == ('blade.png', 'guard.png')
    assert (equip['attr1_image'], equip['attr6_image'], equip['attr30_image']) == ('hat.png', 'cape.png', 'last.png')
    client._handle_packet(3, number(7, 3) + number(36) + text(''))
    game._render_npc(10, 20, npc, 7)
    assert draw.call_args.args[3]['attr1_image'] == ''
    client._handle_packet(3, number(7, 3) + number(10) + number(1) + number(11) + number(0))
    assert npc['sword_power'] == 1 and npc['shield_power'] == 0
    assert npc['sword_image'] == npc['shield_image'] == ''


def test_z_properties_change_player_and_npc_draw_offsets(game, client, monkeypatch):
    classic = client.test_version == '2.22'
    player_z = number(45) + number(52) if classic else number(80) + pixel(2)
    npc_z = number(43) + number(52) if classic else number(77) + pixel(2)
    client._handle_packet(9, player_z)
    client._handle_packet(8, number(8, 2) + player_z)
    client._handle_packet(3, number(7, 3) + number(0) + text('#c#')
                          + number(12) + text('idle') + npc_z)
    assert client.player.z == client.players[8]['z'] == client.npcs[7]['z'] == 2
    draw = Mock()
    monkeypatch.setattr(game, '_render_animated_entity', draw)
    monkeypatch.setattr(game, '_render_swamp_overlay', Mock())
    scale = game.camera.scale
    game._render_player(10, 80, client.player, game.player_anim)
    assert draw.call_args.args[1] == 80 - 2 * scale
    assert draw.call_args.args[3]['_shadow_offset_y'] == 2 * scale
    game._render_other_player(10, 80, client.players[8], 8)
    assert draw.call_args.args[1] == 80 - 2 * scale
    game.npc_anims[7] = SimpleNamespace(set_animation=Mock(), gani=SimpleNamespace(is_movie=False))
    game._render_npc(10, 80, client.npcs[7], 7)
    assert draw.call_args.args[1] == 80 - 2 * scale
    assert draw.call_args.args[3]['_shadow_offset_y'] == 2 * scale


def test_gani_shadow_remains_at_ground_height():
    body = pygame.Surface((2, 2))
    shadow = pygame.Surface((2, 2))
    part = SimpleNamespace(x=0, y=0, width=2, height=2)
    frame = SimpleNamespace(sprites=[])
    anim = SimpleNamespace(gani=SimpleNamespace(name='idle'), get_frame=lambda: frame)
    renderer = SimpleNamespace(screen=Mock(), shadow_sprite=shadow,
                               sprite_mgr=SimpleNamespace(get_sprite=lambda *args: body),
                               _sprite_with_alpha=lambda sprite, alpha: sprite,
                               _resolve_gani_layers=lambda *args: [('shadow', 0, 4), ('sprite', 'body.png', part, 0, 0, False)])
    GaniRenderMixin._render_animated_entity(renderer, 10, 48, anim, {'_shadow_offset_y': 32})
    assert renderer.screen.blit.call_args_list[0].args == (shadow, (10, 84))
    assert renderer.screen.blit.call_args_list[1].args == (body, (10, 48))


def test_modes_preserve_input_and_hud(game, client, monkeypatch):
    input_events = client.on_fullstop = Mock()
    for packet in (176, 177):
        client._handle_packet(packet, b'')
        assert not client.input_frozen
    assert client.classic_mode_disabled
    assert client.server_mode == 'newworld'
    input_events.assert_not_called()
    draw = Mock()
    monkeypatch.setattr(game.hud.ui, 'draw', draw)
    game.hud.draw()
    draw.assert_called_once()


# -- PLO_SERVERWARP: the server names the target, the player consents ----------

WARP_PACKET = b'Target,Target Display,127.0.0.2,15001'


def test_serverwarp_does_not_reconnect_without_consent(game, client):
    client._handle_packet(178, WARP_PACKET)
    assert game.switch_server is None
    assert game.running
    assert game.server_warp_prompt['host'] == '127.0.0.2'
    assert game.server_warp_prompt['port'] == 15001
    for key in (pygame.K_RETURN, pygame.K_n, pygame.K_ESCAPE, pygame.K_a):
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=''))
        game._handle_events()
        assert game.switch_server is None


@pytest.mark.parametrize('key', [pygame.K_RETURN, pygame.K_n, pygame.K_ESCAPE])
def test_serverwarp_default_answer_is_no(game, client, key):
    client._handle_packet(178, WARP_PACKET)
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=''))
    game._handle_events()
    assert game.server_warp_prompt is None
    assert game.switch_server is None
    assert game.running


def _press(game, *keys):
    for key in keys:
        name = pygame.key.name(key)
        pygame.event.post(pygame.event.Event(
            pygame.KEYDOWN, key=key, unicode=name if len(name) == 1 else ''))
        game._handle_events()


def _type_word(game, word):
    _press(game, *[getattr(pygame, 'K_' + letter) for letter in word])


def test_serverwarp_yes_takes_the_server_switch_path(game, client):
    client._handle_packet(178, WARP_PACKET)
    # the confirm is the word "yes" then Enter, once the prompt is armed
    game.server_warp_prompt['opened_at'] -= game.SERVER_WARP_ARM_SECONDS + 1
    _type_word(game, 'warp')
    _press(game, pygame.K_RETURN)
    assert game.switch_server.ip == '127.0.0.2'
    assert game.switch_server.port == 15001
    assert game.switch_server.name == 'Target Display'
    assert not game.running
    assert game.server_warp_prompt is None


def _arm(game):
    game.server_warp_prompt['opened_at'] -= game.SERVER_WARP_ARM_SECONDS + 1


def test_serverwarp_a_stray_or_held_key_never_connects(game, client):
    client._handle_packet(178, WARP_PACKET)
    _type_word(game, 'warp')                   # inside the arming delay
    _press(game, pygame.K_RETURN)              # not armed: Enter declines
    assert game.switch_server is None and game.server_warp_prompt is None
    client.server_warp_declined_until = 0.0
    client._handle_packet(178, WARP_PACKET)
    _arm(game)
    _press(game, *([pygame.K_w] * 10), pygame.K_RETURN)   # a held, repeating key
    assert game.switch_server is None and game.running
    client.server_warp_declined_until = 0.0
    client._handle_packet(178, WARP_PACKET)
    _arm(game)
    _type_word(game, 'war')
    _press(game, pygame.K_RETURN)                         # incomplete word
    assert game.switch_server is None


def test_serverwarp_a_chat_line_ending_in_yes_enter_cannot_confirm(game, client):
    """The old confirm was "yes": a player finishing a chat line could answer
    the prompt by accident. The prompt now closes chat, drops queued key
    events and starts its own empty field, and "yes" is not the word."""
    game.chat.typing = True
    game.chat.input = "see you in a bit, yes"
    pygame.event.post(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_RETURN, unicode='\r'))   # queued
    client._handle_packet(178, WARP_PACKET)
    assert game.chat.typing is False and game.chat.input == ""
    assert game.server_warp_prompt['typed'] == ''
    assert pygame.event.peek(pygame.KEYDOWN) is False          # discarded
    _arm(game)
    _type_word(game, 'yes')
    assert game.server_warp_prompt['typed'] == 'yes'
    _press(game, pygame.K_RETURN)
    assert game.switch_server is None and game.running
    assert game.server_warp_prompt is None


def test_serverwarp_prompt_field_backspace_and_draw(game, client):
    client._handle_packet(178, WARP_PACKET)
    _arm(game)
    _type_word(game, 'wax')
    _press(game, pygame.K_BACKSPACE)
    assert game.server_warp_prompt['typed'] == 'wa'
    game.hud.draw()


def test_blocked_script_warp_shows_a_rate_limited_hud_notice(game, client):
    client._protocol = SimpleNamespace(
        connected=True, send_packet=lambda *a, **k: True)
    client._authenticated = True
    client.note_server_warp_declined()
    assert client.send_server_warp('Somewhere') is False
    assert game.hud_notice is not None and 'F8' in game.hud_notice[0]
    first = game.hud_notice
    client.send_server_warp('Elsewhere')              # inside 5 s: no new notice
    assert game.hud_notice is first
    client.server_warp_notice_at -= client.SERVER_WARP_NOTICE_INTERVAL + 1
    client.send_server_warp('Third')
    assert game.hud_notice is not first
    game.hud.draw()


def test_serverwarp_decline_blocks_new_offers_for_the_cooldown(game, client):
    client._handle_packet(178, WARP_PACKET)
    _press(game, pygame.K_n)
    assert game.server_warp_prompt is None
    client._handle_packet(178, WARP_PACKET)    # a hostile script asks again
    assert game.server_warp_prompt is None
    client.server_warp_declined_until = 0.0    # cooldown over
    client._handle_packet(178, WARP_PACKET)
    assert game.server_warp_prompt is not None


def test_serverwarp_offers_are_capped_per_session(game, client):
    for _ in range(client.SERVER_WARP_MAX_OFFERS):
        client._handle_packet(178, WARP_PACKET)
        assert game.server_warp_prompt is not None
        game.server_warp_prompt = None
    client._handle_packet(178, WARP_PACKET)
    assert game.server_warp_prompt is None
    game._handle_key_press(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F8))
    client._handle_packet(178, WARP_PACKET)    # the player used F8
    assert game.server_warp_prompt is not None


def test_serverwarp_prompt_says_whether_the_target_is_listed(game, client):
    listed = SimpleNamespace(ip='127.0.0.2', port=15001, name='Target')
    game.servers = [listed]
    client._handle_packet(178, WARP_PACKET)
    assert game.server_warp_prompt['in_list'] is True
    game.server_warp_prompt = None
    game.servers = [SimpleNamespace(ip='127.0.0.2', port=15002, name='Other')]
    client._handle_packet(178, WARP_PACKET)
    assert game.server_warp_prompt['in_list'] is False
    # Being listed never skips the prompt.
    assert game.switch_server is None


def test_serverwarp_prompt_draws(game, client):
    client._handle_packet(178, WARP_PACKET)
    game.hud.draw()


def test_serverwarp_second_offer_cannot_replace_an_open_prompt(game, client):
    client._handle_packet(178, WARP_PACKET)
    client._handle_packet(178, b'Evil,Evil,10.0.0.9,9999')
    assert game.server_warp_prompt['host'] == '127.0.0.2'


@pytest.mark.parametrize('payload', [
    b'N,N,,15001',                  # empty host
    b'N,N,host name,15001',         # whitespace
    b'N,N,host\x01name,15001',      # control character
    b'N,N,host\tname,15001',        # tab
    b'N,N,127.0.0.2,0',             # port out of range
    b'N,N,127.0.0.2,65536',
    b'N,N,127.0.0.2,-5',
    b'N,N,127.0.0.2,notaport',
    b'N,N,127.0.0.2',               # truncated
])
def test_serverwarp_rejects_malformed_targets(game, client, payload):
    callback = client.on_server_warp = Mock(wraps=client.on_server_warp)
    client._handle_packet(178, payload)
    assert game.server_warp_prompt is None
    assert game.switch_server is None
    assert client.accept_server_warp() is None


def test_library_never_connects_and_accepts_only_on_request(client):
    seen = []
    client.on_server_warp = seen.append
    client._handle_packet(178, WARP_PACKET)
    assert seen and seen[0]['host'] == '127.0.0.2'
    assert client.server_warp_info is not None
    assert client.accept_server_warp() == {
        'name': 'Target Display', 'host': '127.0.0.2', 'port': 15001}
    assert client.server_warp_info is None


def test_library_accept_refuses_a_malformed_offer(client):
    client._handle_packet(178, b'N,N,bad host,15001')
    assert client.accept_server_warp() is None


def test_serverwarp_raises_the_script_event_when_a_gs2_engine_is_loaded(game, client):
    game.gs2 = Mock()
    client._handle_packet(178, WARP_PACKET)
    game.gs2.trigger_weapon_event.assert_called_once_with(
        'StartScript_Connector', 'onServerWarp', 'Target Display', '127.0.0.2', 15001)
    assert game.switch_server is None


# -- Z/Z2 "unset" sentinels --------------------------------------------------
# GServer-v2 Character.h:75-79: valid Z is -50..170 tiles; unset is -51 tiles,
# serialised as -816 px.

def _npc_with_z2(client, z2_tiles, npc_id=7):
    client._handle_packet(3, number(npc_id, 3) + number(77)
                          + pixel(z2_tiles))
    return client.npcs[npc_id]


def test_npc_z2_server_unset_marker_is_not_a_height(client):
    assert 'z' not in _npc_with_z2(client, -51)


def test_npc_z2_reference_client_marker_is_not_a_height(client):
    assert 'z' not in _npc_with_z2(client, -102)


def test_npc_z2_keeps_the_previous_height_over_an_unset_marker(client):
    _npc_with_z2(client, 3)
    assert _npc_with_z2(client, -51)['z'] == 3


@pytest.mark.parametrize('z', [-50, -1.5, 0, 2.25, 170])
def test_npc_z2_in_range_is_kept(client, z):
    assert _npc_with_z2(client, z)['z'] == z


def test_npc_z2_out_of_range_high_is_dropped(client):
    assert 'z' not in _npc_with_z2(client, 171)


def test_npc_z_tile_byte_unset_is_not_a_height(client):
    client._handle_packet(3, number(7, 3) + number(43) + bytes([255]))
    assert 'z' not in client.npcs[7]


def test_other_player_z2_unset_marker_is_not_a_height(client):
    client.players[8] = {}
    client._handle_packet(8, number(8, 2) + number(80) + pixel(-51))
    assert 'z' not in client.players[8]
    client._handle_packet(8, number(8, 2) + number(80) + pixel(4))
    assert client.players[8]['z'] == 4
    client._handle_packet(8, number(8, 2) + number(80) + pixel(-51))
    assert client.players[8]['z'] == 4


def test_own_z2_unset_marker_leaves_z_at_ground(client):
    client._handle_packet(9, number(80) + pixel(-51))
    assert client.player.z == 0
    client._handle_packet(9, number(80) + pixel(6))
    assert client.player.z == 6
    client._handle_packet(9, number(80) + pixel(-51))
    assert client.player.z == 6


def test_attached_player_inherits_a_sane_npc_z(client):
    from pyreborn.attachments import attachment_z
    client.players[8] = {'_attachment': {'npc_id': 7, 'last_x': 0, 'last_y': 0},
                         'x': 1, 'y': 1}
    _npc_with_z2(client, -51)
    assert attachment_z(client, client.players[8]) == 0
    client.npcs[7]['z'] = -51.0      # a bad value from any other route
    assert attachment_z(client, client.players[8]) == 0
    client.npcs[7]['z'] = 2.0
    assert attachment_z(client, client.players[8]) == 2.0


# -- player show-images on a gmap --------------------------------------------

def _player_showimg(client, player_id):
    client._handle_packet(32, number(player_id, 2) + number(17) + number(0)
                          + text('lamp.png') + number(1) + number(10) + number(2)
                          + number(10) + number(3) + number(1))
    rec = client.players[player_id]['imgs'][7]
    return rec['x'], rec['y']


def _gmap_client(client):
    client.player.level = client._current_level_name = 'chicken.gmap'
    assert client.is_gmap
    client.gmap_name = 'chicken.gmap'
    client.gmap_grid = {(0, 0): 'seg0.nw', (1, 0): 'seg1.nw'}


def test_player_showimg_uses_the_owners_gmaplevelx_when_level_is_the_gmap_file(client):
    _gmap_client(client)
    client.players[7] = {'level': 'chicken.gmap', 'gmaplevelx': 1, 'gmaplevely': 0}
    assert _player_showimg(client, 7) == (5 + 64, 5)


def test_player_showimg_uses_the_segment_name_form(client):
    _gmap_client(client)
    client.players[8] = {'level': 'seg1.nw'}
    assert _player_showimg(client, 8) == (5 + 64, 5)


def test_player_showimg_falls_back_to_the_world_position(client):
    _gmap_client(client)
    client.players[9] = {'level': 'chicken.gmap', 'world_x': 70.0, 'world_y': 5.0}
    assert _player_showimg(client, 9) == (5 + 64, 5)


def test_other_player_props_carry_gmaplevelx_y(client):
    client.players[7] = {}
    client._handle_packet(8, number(7, 2) + number(43) + number(1) + number(44) + number(2))
    assert (client.players[7]['gmaplevelx'], client.players[7]['gmaplevely']) == (1, 2)


# -- NPCMOVED level names / NPC equipment images -----------------------------

def test_npcmoved_level_name_is_resolved_case_insensitively(client):
    client.npcs[7] = {}
    client._handle_packet(24, number(7, 3) + number(4) + number(4) + b'NewLevel.nw')
    assert client.npcs[7]['_level'] == 'newlevel.nw'
    client._handle_packet(24, number(7, 3) + number(4) + number(4) + b'A.NW')
    assert client.npcs[7]['_level'] == 'a.nw'     # the spelling already in use


def _npc_equipment_packet(prop_id, power, image):
    return number(7, 3) + number(prop_id) + number(power) + number(len(image)) + image


def test_npc_sword_and_shield_images_get_png_when_extensionless(client):
    client._handle_packet(3, number(7, 3) + number(10) + number(10 + 30)
                          + number(len(b'blade')) + b'blade')
    assert client.npcs[7]['sword_image'] == 'blade.png'
    client._handle_packet(3, number(7, 3) + number(11) + number(10 + 20)
                          + number(len(b'buckler.gif')) + b'buckler.gif')
    assert client.npcs[7]['shield_image'] == 'buckler.gif'
