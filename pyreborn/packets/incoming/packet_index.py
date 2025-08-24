#!/usr/bin/env python3
"""
Static Packet Module Index

This module provides a static mapping of packet IDs to their module paths.
This is much more efficient than dynamic discovery and ensures packets can
always be found quickly.
"""

# Map packet IDs to their module paths (only existing files verified)
PACKET_MODULE_INDEX = {
    # Core packets
    0: "pyreborn.packets.incoming.core.level_board",
    1: "pyreborn.packets.incoming.core.level_link",
    2: "pyreborn.packets.incoming.npcs.baddy_props", 
    4: "pyreborn.packets.incoming.core.level_chest",
    5: "pyreborn.packets.incoming.core.level_sign",
    6: "pyreborn.packets.incoming.core.level_name",
    8: "pyreborn.packets.incoming.core.other_player_props",
    9: "pyreborn.packets.incoming.core.player_props",
    27: "pyreborn.packets.incoming.core.baddy_hurt",
    41: "pyreborn.packets.incoming.core.start_message",
    
    # Movement packets
    49: "pyreborn.packets.incoming.movement.gmap_warp2",  # GMAP warp with world coords
    189: "pyreborn.packets.incoming.movement.move2",
    
    # Combat packets
    12: "pyreborn.packets.incoming.combat.bomb_del",
    13: "pyreborn.packets.incoming.combat.bomb_add",
    33: "pyreborn.packets.incoming.npcs.npc_weapon_add",
    43: "pyreborn.packets.incoming.combat.default_weapon",
    50: "pyreborn.packets.incoming.combat.hurt_player",
    194: "pyreborn.packets.incoming.combat.clear_weapons",
    
    # NPC packets
    3: "pyreborn.packets.incoming.npcs.npc_props",
    34: "pyreborn.packets.incoming.npcs.npc_weapon_del",
    150: "pyreborn.packets.incoming.npcs.npc_delete",
    
    # Communication packets
    10: "pyreborn.packets.incoming.communication.private_message",
    20: "pyreborn.packets.incoming.communication.to_all",
    
    # System packets
    15: "pyreborn.packets.incoming.system.warp_failed",
    16: "pyreborn.packets.incoming.system.disconnect_message",
    25: "pyreborn.packets.incoming.system.signature",
    28: "pyreborn.packets.incoming.system.flag_set",
    39: "pyreborn.packets.incoming.system.level_modtime",
    42: "pyreborn.packets.incoming.system.newworldtime",
    44: "pyreborn.packets.incoming.system.has_npc_server",
    47: "pyreborn.packets.incoming.system.staff_guilds",
    57: "pyreborn.packets.incoming.system.admin_message",
    60: "pyreborn.packets.incoming.system.player_rights",
    66: "pyreborn.packets.incoming.system.lighting_control",
    75: "pyreborn.packets.incoming.system.profile",
    76: "pyreborn.packets.incoming.system.event_trigger",
    82: "pyreborn.packets.incoming.system.server_text",
    156: "pyreborn.packets.incoming.system.set_active_level",
    182: "pyreborn.packets.incoming.system.list_processes",
    
    # File packets
    68: "pyreborn.packets.incoming.files.large_file_start",
    69: "pyreborn.packets.incoming.files.large_file_end",
    84: "pyreborn.packets.incoming.files.large_file_size",
    100: "pyreborn.packets.incoming.files.raw_data",
    101: "pyreborn.packets.incoming.files.board_packet",
    102: "pyreborn.packets.incoming.files.file",  # File transfer (PLO_FILE)
    160: "pyreborn.packets.incoming.files.file",
    161: "pyreborn.packets.incoming.files.file_uptodate",
    
    # UI packets
    32: "pyreborn.packets.incoming.ui.show_img",
    174: "pyreborn.packets.incoming.ui.ghost_icon",
    175: "pyreborn.packets.incoming.ui.ghost_mode",
    179: "pyreborn.packets.incoming.ui.rpg_window",
    180: "pyreborn.packets.incoming.ui.status_list",
    
    # Item packets
    23: "pyreborn.packets.incoming.items.item_del",
    24: "pyreborn.packets.incoming.items.item_add",
    
    # Animal packets
    18: "pyreborn.packets.incoming.animals.horse_del",
    19: "pyreborn.packets.incoming.animals.horse_add",
    
    # Effect packets
    183: "pyreborn.packets.incoming.effects.explosion",
    
    # RC packets
    64: "pyreborn.packets.incoming.rc.rc_chat",
    74: "pyreborn.packets.incoming.rc.rc_admin_message",
    
    # Scripting packets
    134: "pyreborn.packets.incoming.scripting.gani_script",
    
    # Unknown/Reserved packets
    168: "pyreborn.packets.incoming.unknown.packet_168",
    190: "pyreborn.packets.incoming.unknown.packet_190",
    194: "pyreborn.packets.incoming.unknown.packet_194",
}

# Preload all packet modules for fast access
_loaded_modules = {}

def get_packet_module(packet_id: int):
    """Get the module for a packet ID (cached)"""
    if packet_id not in PACKET_MODULE_INDEX:
        return None
        
    module_path = PACKET_MODULE_INDEX[packet_id]
    
    # Check cache first
    if module_path in _loaded_modules:
        return _loaded_modules[module_path]
    
    # Load and cache the module
    try:
        import importlib
        module = importlib.import_module(module_path)
        _loaded_modules[module_path] = module
        return module
    except ImportError:
        return None

def preload_all_modules():
    """Preload all packet modules for maximum performance"""
    import importlib
    for packet_id, module_path in PACKET_MODULE_INDEX.items():
        if module_path not in _loaded_modules:
            try:
                module = importlib.import_module(module_path)
                _loaded_modules[module_path] = module
            except ImportError:
                pass