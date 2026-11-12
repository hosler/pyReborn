"""Derived state aliases, component reset(), derived packets exports, and the
dropped-socket notification.

The old hand-kept tables are snapshotted below so the derivation is proven to
reproduce them exactly.
"""

import pytest

from pyreborn import client_state as cs
from pyreborn.client import Client, _STATE_ALIASES

# _STATE_ALIASES as it was hand-written before it was derived (178 rows).
OLD_STATE_ALIASES = {
    '_adjacent_level_requests': ('level_state', 'adjacent_level_requests'),
    '_arrow_hurt_suppress': ('combat_state', 'arrow_hurt_suppress'),
    '_arrow_sims': ('combat_state', 'arrow_sims'),
    '_authenticated': ('session', 'authenticated'),
    '_awaiting_warp_confirm': ('warp_state', 'awaiting_warp_confirm'),
    '_board_layers_level_name': ('level_state', 'board_layers_level_name'),
    '_cache_index': ('file_transfers', 'cache_index'),
    '_colors_len': ('session', 'colors_len'),
    '_current_level_name': ('level_state', 'current_level_name'),
    '_failed_files': ('file_transfers', 'failed_files'),
    '_file_attempts': ('file_transfers', 'file_attempts'),
    '_file_no_modtime': ('session', 'file_no_modtime'),
    '_gmap_offset_x': ('gmap_state', 'gmap_offset_x'),
    '_gmap_offset_y': ('gmap_state', 'gmap_offset_y'),
    '_gmap_spawn_x': ('gmap_state', 'gmap_spawn_x'),
    '_gmap_spawn_y': ('gmap_state', 'gmap_spawn_y'),
    '_gs2_requested': ('scripts', 'gs2_requested'),
    '_handled_plo_ids': ('instrumentation', 'handled_plo_ids'),
    '_in_update': ('session', 'in_update'),
    '_known_gmap_segments': ('gmap_state', 'known_gmap_segments'),
    '_large_file_transfers': ('file_transfers', 'large_file_transfers'),
    '_last_gmap_name': ('gmap_state', 'last_gmap_name'),
    '_local_arrow_reports': ('combat_state', 'local_arrow_reports'),
    '_local_level_transition': ('warp_state', 'local_level_transition'),
    '_local_level_transition_direction': ('warp_state', 'local_level_transition_direction'),
    '_local_level_transition_epoch': ('warp_state', 'local_level_transition_epoch'),
    '_local_level_transition_started': ('warp_state', 'local_level_transition_started'),
    '_login_time': ('session', 'login_time'),
    '_npc_cache': ('entities', 'npc_cache'),
    '_npc_pos_epoch': ('entities', 'npc_pos_epoch'),
    '_own_recent_arrows': ('combat_state', 'own_recent_arrows'),
    '_pending_arrow_hits': ('combat_state', 'pending_arrow_hits'),
    '_pending_board_level_name': ('level_state', 'pending_board_level_name'),
    '_pending_files': ('file_transfers', 'pending_files'),
    '_pending_level_name': ('level_state', 'pending_level_name'),
    '_plain_level_change_epoch': ('warp_state', 'plain_level_change_epoch'),
    '_raw_data_expected': ('session', 'raw_data_expected'),
    '_received_files': ('file_transfers', 'received_files'),
    '_requested_files': ('file_transfers', 'requested_files'),
    '_requested_gmap': ('gmap_state', 'requested_gmap'),
    '_tiles_level_name': ('level_state', 'tiles_level_name'),
    '_update_packages': ('file_transfers', 'update_packages'),
    '_uptodate_files': ('file_transfers', 'uptodate_files'),
    '_use_pixel_props': ('session', 'use_pixel_props'),
    '_warned_packet_errors': ('instrumentation', 'warned_packet_errors'),
    '_warp_echo': ('warp_state', 'warp_echo'),
    '_warp_fallback': ('warp_state', 'warp_fallback'),
    'active_explosions': ('entities', 'active_explosions'),
    'active_level': ('level_state', 'active_level'),
    'all_players': ('entities', 'all_players'),
    'arrows': ('entities', 'arrows'),
    'auto_respond_hurt': ('combat_state', 'auto_respond_hurt'),
    'baddies': ('entities', 'baddies'),
    'bigmap_info': ('gmap_state', 'bigmap_info'),
    'board_heights': ('level_state', 'board_heights'),
    'board_layers': ('level_state', 'board_layers'),
    'bombs': ('entities', 'bombs'),
    'chest_items': ('level_state', 'chest_items'),
    'chest_signs': ('level_state', 'chest_signs'),
    'chests': ('level_state', 'chests'),
    'classic_mode_disabled': ('session', 'classic_mode_disabled'),
    'default_weapon': ('session', 'default_weapon'),
    'disconnect_reason': ('session', 'disconnect_reason'),
    'frozen': ('session', 'frozen'),
    'gani_setbackto': ('scripts', 'gani_setbackto'),
    'ghost_icon': ('session', 'ghost_icon'),
    'ghost_mode': ('session', 'ghost_mode'),
    'global_flags': ('session', 'global_flags'),
    'gmap_grid': ('gmap_state', 'gmap_grid'),
    'gmap_height': ('gmap_state', 'gmap_height'),
    'gmap_name': ('gmap_state', 'gmap_name'),
    'gmap_width': ('gmap_state', 'gmap_width'),
    'gs1_host': ('scripts', 'gs1_host'),
    'gs2_bytecode': ('scripts', 'gs2_bytecode'),
    'gs2_host': ('scripts', 'gs2_host'),
    'gs2_script_headers': ('scripts', 'gs2_script_headers'),
    'has_npc_server': ('session', 'has_npc_server'),
    'hide_player_hearts': ('session', 'hide_player_hearts'),
    'hide_player_until': ('session', 'hide_player_until'),
    'horses': ('entities', 'horses'),
    'hurt_animation': ('combat_state', 'hurt_animation'),
    'input_frozen': ('session', 'input_frozen'),
    'is_leader': ('level_state', 'is_leader'),
    'item_clock': ('entities', 'item_clock'),
    'item_stamps': ('entities', 'item_stamps'),
    'items': ('entities', 'items'),
    'last_server_warp': ('session', 'last_server_warp'),
    'last_server_warp_at': ('session', 'last_server_warp_at'),
    'level_modtimes': ('level_state', 'level_modtimes'),
    'levels': ('level_state', 'levels'),
    'links': ('level_state', 'links'),
    'login_complete': ('session', 'login_complete'),
    'minimap_info': ('gmap_state', 'minimap_info'),
    'net_cookie': ('session', 'net_cookie'),
    'npc_moves': ('entities', 'npc_moves'),
    'npcs': ('entities', 'npcs'),
    'npcs_hidden': ('session', 'npcs_hidden'),
    'npcserver_addr': ('session', 'npcserver_addr'),
    'on_add_player': ('callbacks', 'on_add_player'),
    'on_arrow_add': ('callbacks', 'on_arrow_add'),
    'on_baddy': ('callbacks', 'on_baddy'),
    'on_baddy_hurt': ('callbacks', 'on_baddy_hurt'),
    'on_board_layer': ('callbacks', 'on_board_layer'),
    'on_board_modify': ('callbacks', 'on_board_modify'),
    'on_bomb_add': ('callbacks', 'on_bomb_add'),
    'on_bomb_del': ('callbacks', 'on_bomb_del'),
    'on_bomb_exploded': ('callbacks', 'on_bomb_exploded'),
    'on_bush_cut': ('callbacks', 'on_bush_cut'),
    'on_chat': ('callbacks', 'on_chat'),
    'on_chest': ('callbacks', 'on_chest'),
    'on_del_player': ('callbacks', 'on_del_player'),
    'on_disconnect': ('callbacks', 'on_disconnect'),
    'on_explosion': ('callbacks', 'on_explosion'),
    'on_file': ('callbacks', 'on_file'),
    'on_file_send_failed': ('callbacks', 'on_file_send_failed'),
    'on_file_uptodate': ('callbacks', 'on_file_uptodate'),
    'on_firespy': ('callbacks', 'on_firespy'),
    'on_flag': ('callbacks', 'on_flag'),
    'on_flag_del': ('callbacks', 'on_flag_del'),
    'on_freeze': ('callbacks', 'on_freeze'),
    'on_fullstop': ('callbacks', 'on_fullstop'),
    'on_ghost_mode': ('callbacks', 'on_ghost_mode'),
    'on_gs2_bytecode': ('callbacks', 'on_gs2_bytecode'),
    'on_hide_npcs': ('callbacks', 'on_hide_npcs'),
    'on_hit_objects': ('callbacks', 'on_hit_objects'),
    'on_horse_add': ('callbacks', 'on_horse_add'),
    'on_horse_del': ('callbacks', 'on_horse_del'),
    'on_hurt': ('callbacks', 'on_hurt'),
    'on_item': ('callbacks', 'on_item'),
    'on_leaps': ('callbacks', 'on_leaps'),
    'on_level': ('callbacks', 'on_level'),
    'on_login_complete': ('callbacks', 'on_login_complete'),
    'on_minimap': ('callbacks', 'on_minimap'),
    'on_npc_del': ('callbacks', 'on_npc_del'),
    'on_npc_move': ('callbacks', 'on_npc_move'),
    'on_npc_moved': ('callbacks', 'on_npc_moved'),
    'on_packages_download_complete': ('callbacks', 'on_packages_download_complete'),
    'on_packet': ('callbacks', 'on_packet'),
    'on_player_left': ('callbacks', 'on_player_left'),
    'on_pm': ('callbacks', 'on_pm'),
    'on_profile': ('callbacks', 'on_profile'),
    'on_projectile': ('callbacks', 'on_projectile'),
    'on_pushaway': ('callbacks', 'on_pushaway'),
    'on_rpg_window': ('callbacks', 'on_rpg_window'),
    'on_say2': ('callbacks', 'on_say2'),
    'on_server_text': ('callbacks', 'on_server_text'),
    'on_server_warp': ('callbacks', 'on_server_warp'),
    'on_server_warp_blocked': ('callbacks', 'on_server_warp_blocked'),
    'on_sign': ('callbacks', 'on_sign'),
    'on_start_message': ('callbacks', 'on_start_message'),
    'on_sword_hit_npc': ('callbacks', 'on_sword_hit_npc'),
    'on_throwcarried': ('callbacks', 'on_throwcarried'),
    'on_triggeraction': ('callbacks', 'on_triggeraction'),
    'on_update_package_downloaded': ('callbacks', 'on_update_package_downloaded'),
    'on_update_package_failed': ('callbacks', 'on_update_package_failed'),
    'on_update_package_progress': ('callbacks', 'on_update_package_progress'),
    'on_weapon_add': ('callbacks', 'on_weapon_add'),
    'packet_stats': ('instrumentation', 'packet_stats'),
    'player_list': ('entities', 'player_list'),
    'players': ('entities', 'players'),
    'profiles': ('session', 'profiles'),
    'prop_parse_diagnostics': ('instrumentation', 'prop_parse_diagnostics'),
    'rpg_window_lines': ('session', 'rpg_window_lines'),
    'server_message': ('session', 'server_message'),
    'server_mode': ('session', 'server_mode'),
    'server_signature': ('session', 'server_signature'),
    'server_text': ('session', 'server_text'),
    'server_time': ('session', 'server_time'),
    'server_warp_declined_until': ('session', 'server_warp_declined_until'),
    'server_warp_info': ('session', 'server_warp_info'),
    'server_warp_notice_at': ('session', 'server_warp_notice_at'),
    'server_warp_offers': ('session', 'server_warp_offers'),
    'sign_lists': ('level_state', 'sign_lists'),
    'signs': ('level_state', 'signs'),
    'staff_guilds': ('session', 'staff_guilds'),
    'status_list': ('session', 'status_list'),
    'tiles': ('level_state', 'tiles'),
    'weapons': ('entities', 'weapons'),
}

# Public + underscore names of pyreborn.packets as the hand-kept export list
# produced them (non-dunder).
OLD_PACKET_EXPORTS = [
    'Any', 'BADDY_PROPS', 'BDPROP', 'COLORS_CLASSIC', 'Dict',
    'GUPD_BYTES_MAX', 'GUPD_LINE_MAX', 'LEVEL_ITEM_NAMES',
    'NPC_CLASS_LIST_MAX', 'NPC_PROPS', 'Optional', 'PLAYER_PROPS', 'PLI',
    'PLO', 'PLPROP', 'PacketBuilder', 'PacketID', 'PacketReader',
    'StreamPolicy', 'UPDATE_PACKAGE_FILES_MAX', 'UPDATE_PACKAGE_NAME_MAX',
    '_ADDPLAYER_BYTE_PROPS', '_ADDPLAYER_STR_PROPS', '_BADDY_PROP_HANDLERS',
    '_BADDY_STREAM', '_GATTRIB_IDS', '_GATTRIB_PROP', '_NPC_PROP_HANDLERS',
    '_NPC_STREAM', '_NPC_TEXT_KEYS', '_OTHER_PROP_HANDLERS',
    '_OTHER_STREAM', '_PLAYER_STREAM', '_SELF_PROP_HANDLERS',
    '_SIGN_ALPHABET', '_SIGN_CTAB', '_SIGN_CTABINDEX', '_SIGN_SYMBOLS',
    '_build_rc_props_tail', '_gattrib_handlers', '_gint3', '_gtokenize',
    '_guntokenize', '_parse_npc_props_once', '_parse_reborn_csv',
    '_parse_script_header', '_parse_weapon_add_structured',
    '_parse_weapon_add_text', '_parse_with_colors_retry', '_raw',
    '_read_gbyte', '_read_string', '_round_position', '_set',
    '_set_head_image', '_set_power_image', '_set_scaled', '_set_sprite',
    '_set_text', '_untokenize_csv_fields', 'build_animation',
    'build_arrow_add', 'build_arrow_count', 'build_attack_player',
    'build_baddy_add', 'build_baddy_hurt', 'build_baddy_props',
    'build_board_modify', 'build_bomb_add', 'build_bomb_count',
    'build_bomb_del', 'build_chat', 'build_claim_pker',
    'build_explosion_add', 'build_firespy', 'build_flag_del',
    'build_flag_set', 'build_hearts', 'build_hit_objects',
    'build_horse_add', 'build_horse_del', 'build_hurt_response',
    'build_item_add', 'build_item_take', 'build_level_warp',
    'build_movement', 'build_nc_classadd', 'build_nc_classdelete',
    'build_nc_classedit', 'build_nc_levellistget', 'build_nc_localnpcsget',
    'build_nc_npcadd', 'build_nc_npcdelete', 'build_nc_npcflagsget',
    'build_nc_npcflagsset', 'build_nc_npcget', 'build_nc_npcreset',
    'build_nc_npcscriptget', 'build_nc_npcscriptset', 'build_nc_npcwarp',
    'build_nc_weaponadd', 'build_nc_weapondelete', 'build_nc_weaponget',
    'build_nc_weaponlistget', 'build_npc_props', 'build_open_chest',
    'build_player_chat', 'build_player_gattrib', 'build_player_props',
    'build_private_message', 'build_profile_get', 'build_profile_set',
    'build_putnpc', 'build_rc_account_add', 'build_rc_account_del',
    'build_rc_account_get', 'build_rc_account_list_get',
    'build_rc_account_set', 'build_rc_admin_message',
    'build_rc_apincrement_set', 'build_rc_apply_reason',
    'build_rc_baddyrespawn_set', 'build_rc_chat',
    'build_rc_disconnect_player', 'build_rc_disconnect_rc',
    'build_rc_filebrowser_cd', 'build_rc_filebrowser_delete',
    'build_rc_filebrowser_download', 'build_rc_filebrowser_end',
    'build_rc_filebrowser_move', 'build_rc_filebrowser_rename',
    'build_rc_filebrowser_start', 'build_rc_filebrowser_up',
    'build_rc_folder_config_get', 'build_rc_folder_delete',
    'build_rc_folderconfig_set', 'build_rc_horselife_set',
    'build_rc_largefile_end', 'build_rc_largefile_start',
    'build_rc_listrcs', 'build_rc_npcserverquery',
    'build_rc_player_ban_get', 'build_rc_player_ban_set',
    'build_rc_player_comments_get', 'build_rc_player_comments_set',
    'build_rc_player_props_get', 'build_rc_player_props_get_by_name',
    'build_rc_player_rights_get', 'build_rc_playerprops_reset',
    'build_rc_playerprops_set', 'build_rc_playerprops_set2',
    'build_rc_playerrights_set', 'build_rc_priv_admin_message',
    'build_rc_respawn_set', 'build_rc_server_flags_get',
    'build_rc_server_options_get', 'build_rc_serverflags_set',
    'build_rc_serveroptions_set', 'build_rc_update_levels',
    'build_rc_warp_player', 'build_shoot', 'build_shoot_v1',
    'build_sword_attack', 'build_throwcarried', 'build_triggeraction',
    'build_update_class', 'build_update_file', 'build_update_gani',
    'build_update_package_request', 'build_update_script', 'build_wantfile',
    'build_weapon_add', 'clean_class_list', 'decode_sign_text',
    'gupd_name_reserved', 'math', 'parse_arrow_add', 'parse_baddy_hurt',
    'parse_baddy_props', 'parse_bigmap', 'parse_board_heights',
    'parse_board_layer', 'parse_board_modify', 'parse_board_modify2',
    'parse_board_packet', 'parse_bomb_add', 'parse_bomb_del', 'parse_chat',
    'parse_class_bytecode_v4', 'parse_default_weapon', 'parse_explosion',
    'parse_file', 'parse_file_uptodate', 'parse_filesendfailed',
    'parse_firespy', 'parse_flag_del', 'parse_flag_set', 'parse_fullstop',
    'parse_fullstop2', 'parse_gani_script', 'parse_ghost_icon',
    'parse_gupd', 'parse_hit_objects', 'parse_horse_add', 'parse_horse_del',
    'parse_hurt_player', 'parse_item_add', 'parse_item_del',
    'parse_large_file_marker', 'parse_large_file_size', 'parse_level_board',
    'parse_level_chest', 'parse_level_link', 'parse_level_modtime',
    'parse_level_name', 'parse_level_sign', 'parse_loadgani',
    'parse_loadscript', 'parse_minimap', 'parse_move', 'parse_move2',
    'parse_nc_class_add', 'parse_nc_class_delete', 'parse_nc_class_get',
    'parse_nc_level_dump', 'parse_nc_level_list', 'parse_nc_npc_add',
    'parse_nc_npc_attributes', 'parse_nc_npc_delete', 'parse_nc_npc_flags',
    'parse_nc_npc_script', 'parse_nc_weapon_get', 'parse_nc_weapon_list',
    'parse_newworldtime', 'parse_npc_bytecode', 'parse_npc_props',
    'parse_npc_showimgs', 'parse_npcdel2', 'parse_npcmoved',
    'parse_npcserveraddr', 'parse_npcweapondel', 'parse_npcweaponscript',
    'parse_other_player', 'parse_player_movement', 'parse_player_props',
    'parse_playerwarp', 'parse_playerwarp2', 'parse_private_message',
    'parse_profile', 'parse_prop_stream', 'parse_push_away',
    'parse_rawdata', 'parse_rc_account_get', 'parse_rc_account_list',
    'parse_rc_add_player', 'parse_rc_admin_message', 'parse_rc_chat',
    'parse_rc_del_player', 'parse_rc_filebrowser_dir',
    'parse_rc_filebrowser_dirlist', 'parse_rc_filebrowser_message',
    'parse_rc_folder_config', 'parse_rc_max_upload_size',
    'parse_rc_player_ban', 'parse_rc_player_comments',
    'parse_rc_player_props', 'parse_rc_player_rights',
    'parse_rc_server_flags', 'parse_rc_server_options', 'parse_rpg_window',
    'parse_say2', 'parse_server_text', 'parse_server_warp',
    'parse_set_active_level', 'parse_setnetcookie', 'parse_shoot',
    'parse_signature', 'parse_staff_guilds', 'parse_start_message',
    'parse_status_list', 'parse_throwcarried', 'parse_triggeraction_in',
    'parse_update_package_done', 'parse_update_package_size',
    'parse_weapon_add', 'parse_weapon_bytecode_v4', 'parse_weapon_hash_v4'
]


def test_derived_aliases_equal_old_hand_table():
    assert _STATE_ALIASES == OLD_STATE_ALIASES
    assert len(_STATE_ALIASES) == 178


def test_every_alias_is_an_installed_property():
    for name in OLD_STATE_ALIASES:
        assert isinstance(getattr(Client, name), property)


def _fresh(cls):
    return cls(*cls._default_args())


def _snapshot(obj):
    out = {}
    for name in type(obj).state_fields():
        value = getattr(obj, name)
        if name == 'tiletypes':
            value = vars(value)
        out[name] = value
    return out


@pytest.mark.parametrize('component', sorted(cs.COMPONENT_CLASSES))
def test_reset_restores_declared_defaults(component):
    cls = cs.COMPONENT_CLASSES[component]
    obj = _fresh(cls)
    held = {}
    for name in cls.state_fields():
        value = getattr(obj, name)
        if isinstance(value, (dict, list, set)):
            held[name] = value          # reference that must survive reset()
            if isinstance(value, dict):
                value['dirty'] = 1
            elif isinstance(value, list):
                value.append('dirty')
            else:
                value.add('dirty')
    for name in cls.state_fields():
        if name not in held and name != 'tiletypes':
            setattr(obj, name, object())   # replace what is not a container
    obj.reset()
    assert _snapshot(obj) == _snapshot(_fresh(cls))
    for name, ref in held.items():
        assert getattr(obj, name) is ref   # cleared in place


def test_reset_named_fields_leaves_others_alone():
    session = cs.SessionState("6.037")
    session.server_mode = 'newworld'
    session.server_message = 'hello'
    session.reset('server_mode')
    assert session.server_mode == ''
    assert session.server_message == 'hello'


def test_reset_keeps_constructor_derived_defaults():
    session = cs.SessionState("1.41")
    assert session.file_no_modtime is True
    session.file_no_modtime = False
    session.reset()
    assert session.file_no_modtime is True
    inst = cs.Instrumentation({1, 2})
    inst.handled_plo_ids.add(99)
    inst.reset()
    assert inst.handled_plo_ids == {1, 2}


def test_client_connect_resets_session_fields(monkeypatch):
    client = Client("127.0.0.1", 1)
    monkeypatch.setattr(client._protocol, 'connect', lambda: True)
    client.server_mode = 'newworld'
    client.server_warp_offers = 3
    client.items['lvl'] = {(1, 2): 'x'}
    client.item_stamps[('lvl', (1, 2))] = 1.0
    client.prop_parse_diagnostics['errors'] = 7
    items_ref = client.items
    assert client.connect() is True
    assert client.server_mode == '' and client.server_warp_offers == 0
    assert client.items == {} and client.items is items_ref
    assert client.item_stamps == {}
    assert client.prop_parse_diagnostics == {
        'warnings': 0, 'errors': 0, 'width_fallbacks': 0}


def test_packets_exports_are_the_old_set_and_are_derived():
    import pyreborn.packets as packets
    current = {n for n in vars(packets) if not n.startswith('__')}
    # Deleted as dead code in the same change (no caller in any repo).
    removed = {'build_firespy', 'build_profile_set', 'parse_fullstop2',
               'parse_level_board', 'parse_player_movement'}
    old = set(OLD_PACKET_EXPORTS) - removed
    assert old <= current, sorted(old - current)
    # Nothing beyond the old names is exported today. A NEW parser added to a
    # packet_codec module is exported automatically; extend OLD_PACKET_EXPORTS
    # only if that is intended to be part of this pinned set.
    from pyreborn.packet_codec import (common, level, player, gameplay,
                                       files, rc, nc)
    defined = set()
    for mod in (common, level, player, gameplay, files, rc, nc):
        defined |= {n for n in vars(mod) if not n.startswith('__')}
    assert current - old <= defined


def test_packets_exports_resolve_to_codec_objects():
    import pyreborn.packets as packets
    from pyreborn.packet_codec import files, gameplay
    assert packets.parse_gupd is files.parse_gupd
    assert packets.build_shoot is gameplay.build_shoot


# --- dropped socket -------------------------------------------------------

class _FakeProtocol:
    def __init__(self):
        self.connected = True
        self.on_disconnect = None
        self.queued = []

    def recv_packets(self, timeout=0.01):
        out, self.queued = self.queued, []
        return out

    def disconnect(self):
        self.connected = False

    def drop(self):
        # Same contract as Protocol._connection_lost()
        was, self.connected = self.connected, False
        if was and self.on_disconnect:
            self.on_disconnect()


def _client_with_fake():
    client = Client("127.0.0.1", 1)
    fake = _FakeProtocol()
    client._protocol = fake
    fake.on_disconnect = client._on_protocol_disconnect
    return client, fake


def test_socket_drop_fires_on_disconnect_once():
    client, fake = _client_with_fake()
    calls = []
    client.on_disconnect = calls.append
    fake.drop()
    assert client.connected is False
    client.update()
    client.update()
    assert calls == ["Connection lost"]
    client.disconnect()              # explicit disconnect afterwards: silent
    client.update()
    assert calls == ["Connection lost"]


def test_explicit_disconnect_does_not_fire():
    client, fake = _client_with_fake()
    calls = []
    client.on_disconnect = calls.append
    client.disconnect()
    fake.drop()                      # transport event after the explicit close
    client.update()
    assert calls == []


def test_disc_message_then_drop_fires_once_with_reason():
    from pyreborn.packets import PacketID
    client, fake = _client_with_fake()
    calls = []
    client.on_disconnect = calls.append
    fake.queued = [(int(PacketID.PLO_DISCMESSAGE), b"Banned")]
    fake.drop()
    client.update()
    assert calls == ["Banned"]


def test_reconnect_rearms_the_notification(monkeypatch):
    client, fake = _client_with_fake()
    calls = []
    client.on_disconnect = calls.append
    fake.drop()
    client.update()
    fake.connected = True
    monkeypatch.setattr(fake, 'connect', lambda: True, raising=False)
    client.connect()
    fake.drop()
    client.update()
    assert len(calls) == 2


def test_real_protocol_fires_callback_on_eof_only_once():
    import socket as _socket
    from pyreborn.protocol import Protocol
    proto = Protocol("127.0.0.1", 1)
    a, b = _socket.socketpair()
    proto.socket = a
    proto.connected = True
    fired = []
    proto.on_disconnect = lambda: fired.append(1)
    b.close()
    proto.recv_packets(0.1)
    proto.recv_packets(0.1)
    assert fired == [1] and proto.connected is False
    # explicit disconnect on a live socket never fires
    c, d = _socket.socketpair()
    proto2 = Protocol("127.0.0.1", 1)
    proto2.socket, proto2.connected = c, True
    proto2.on_disconnect = lambda: fired.append(2)
    proto2.disconnect()
    assert fired == [1]
    d.close()


def test_raising_on_disconnect_does_not_escape_update_and_tail_runs():
    # The "tail" is the simulation tick a headless update() runs once a tick
    # of frame time has passed (Client.run_tick).
    client, fake = _client_with_fake()
    frame = [0.0]
    client.clock.set_sources(source=lambda: frame[0])
    client.update(timeout=0)         # the headless pump starts measuring
    ticks = []
    client.expire_items = lambda: ticks.append('items')

    def boom(reason):
        raise RuntimeError("subscriber bug")

    client.on_disconnect = boom
    fake.drop()
    frame[0] += client.clock.tick_length
    client.update(timeout=0)         # must not raise
    assert ticks == ['items']


def test_failed_login_send_never_fires_on_disconnect_later():
    client, fake = _client_with_fake()
    calls = []
    client.on_disconnect = calls.append

    def failing_send_login(user, password):
        fake.drop()                  # send_packet failure path
        return False

    fake.send_login = failing_send_login
    assert client.login("u", "p", timeout=0.2) is False
    client.update()
    client.update()
    assert calls == []


def test_login_timeout_with_socket_up_still_reports_a_later_real_drop():
    client, fake = _client_with_fake()
    calls = []
    client.on_disconnect = calls.append
    fake.send_login = lambda user, password: True
    assert client.login("u", "p", timeout=0.2) is False
    assert fake.connected
    client._authenticated = True     # the app keeps the connection and retries
    fake.drop()
    client.update()
    client.update()
    assert calls == ["Connection lost"]


def test_eof_during_login_wait_never_fires_on_disconnect():
    client, fake = _client_with_fake()
    calls = []
    client.on_disconnect = calls.append
    fake.send_login = lambda user, password: (fake.drop(), True)[1]
    assert client.login("u", "p", timeout=1.0) is False
    client.update()
    assert calls == []
    # a fresh session re-arms the notification
    fake.connected = True
    fake.connect = lambda: True
    client.connect()
    client._authenticated = True
    fake.drop()
    client.update()
    assert calls == ["Connection lost"]
