"""The package provides compatibility exports for the GS1 client."""

from . import registry as _registry
from . import board as _board
from . import objects as _objects
from . import host_builtins as _host_builtins
from . import host_commands_pre as _host_commands_pre
from . import host_commands_layer as _host_commands_layer
from . import host_commands_npc as _host_commands_npc
from . import host_commands_main as _host_commands_main
from . import host_functions as _host_functions
from . import host as _host
from . import runtime as _runtime

_modules = (
    _registry, _board, _objects, _host_builtins, _host_commands_pre,
    _host_commands_layer, _host_commands_npc, _host_commands_main,
    _host_functions, _host, _runtime,
)
_export_names = [
    'A_CLASS_NPC_ATTR', 'A_CLASS_PLAYER_ATTR', 'ClientGS1', 'Context',
    'GS1ClientHost', 'GS1NoBoard', 'GS2Object', 'Host', 'Interpreter',
    'NAMESPACES', 'NPC_ATTR', 'PLAYER_ATTR', 'PREEMPTED', 'Parser',
    'ParticleEmitter', 'REBORN_PALETTE', 'REBORN_PALETTE_ALIASES', 'TileType',
    'UNSET', 'VarStore', '_BADDY_DEFAULT_IMAGE', '_BADDY_DEFAULT_POWER',
    '_BADDY_TYPES', '_CHARPROP_NPC', '_CHARPROP_PLAYER',
    '_ClientScopeVarStore', '_DEFAULT_IMAGE_PX', '_FALL_THROUGH',
    '_GS1ObjectRef', '_GS1_BUILTINS', '_GS1_DEBUG', '_GS1_ERR_SEEN',
    '_GS1_LAYER_COMMANDS', '_GS1_MAIN_COMMANDS', '_GS1_NPC_BUILTINS',
    '_GS1_NPC_COMMANDS', '_GS1_NPC_TAIL_COMMANDS', '_GS1_PLAYER_BUILTINS',
    '_GS1_PREEMPT_BOARD_WAIT_FRAMES', '_GS1_PRE_COMMANDS',
    '_GS1_STATEMENTS_PER_SLICE', '_ITEM_ID_CACHE', '_NOOP', '_NPC_WRITE',
    '_ONWALL2_EDGE_TOL', '_PlayerFlagScope', '_RefNamespaceInterpreter',
    '_ServerFlagScope', '_TIMEOUT_CANCEL', '_baddy_type_from_name',
    '_board_list', '_board_locate', '_color_code_slot', '_color_name',
    '_gs1_builtin', '_gs1_command', '_is_color_code', '_item_ids',
    '_num_or_str', '_pcode', '_push_dir', '_report_gs1_error',
    '_version_number', 'annotations', 'ast', 'board_tile_read',
    'board_tile_write', 'board_update_region', 'board_world_dims',
    'get_tile_type', 'host_value', 'level_index', 'logger', 'logging', 'math',
    'os', 'register_tiledef', 'remove_tiledefs', 'segment_at', 'sys',
    'tilestype_for_level', 'to_num', 'to_str', 'tokenize', 'tokens_count',
    'traceback', 'type_is_blocking', 'world_to_local',
]
for _export_name in _export_names:
    for _module in _modules:
        if hasattr(_module, _export_name):
            globals()[_export_name] = getattr(_module, _export_name)
            break
    else:
        raise ImportError(f'missing GS1 client compatibility export: {_export_name}')
del _registry, _board, _objects, _host_builtins, _host_commands_pre
del _host_commands_layer, _host_commands_npc, _host_commands_main
del _host_functions, _host, _runtime
del _modules, _export_names, _export_name, _module
