"""Client-side GS2 bytecode execution for pyReborn.

Runs GS2 scripts (weapons/NPCs/classes/ganis) received as compiled bytecode
(PLO_NPCWEAPONSCRIPT / PLO_NPCBYTECODE / PLO_LOADSCRIPT / PLO_GANISCRIPT)
with the shared VM from ``reborn_protocol.gs2``.

Builtins route through the SAME client host surface the GS1 engine uses
(GS1ClientHost in gs1_client.py): showimg/changeimg*/showtext layers land in
the same layer store the pygame renderer draws, say/play/triggeraction fire
the same ``on_*`` callbacks, and player props read/write the same Player
handle. GS2-only surfaces with no GS1 equivalent (GUI controls etc.) are
log-stubbed once per name and show up in GS2VM.coverage_report()'s
builtins_missing.

Wiring mirrors ClientGS1: the embedding app creates ``ClientGS2(client, gs1)``
and calls ``attach()``; inbound bytecode then loads automatically via
client.on_gs2_bytecode, inbound PLO_TRIGGERACTION fires onAction<name>
handlers (client.gs2_host), and the game loop pumps process_timeouts(dt).
"""

from . import registry as _registry
from . import helpers as _helpers
from . import objects as _objects
from . import objects_player as _objects_player
from . import host_any as _host_any
from . import host_collections as _host_collections
from . import host_engine as _host_engine
from . import host_gui as _host_gui
from . import host_objmethods as _host_objmethods
from . import host_particles as _host_particles
from . import host_vars as _host_vars
from . import host_bare as _host_bare
from . import host_objects as _host_objects
from . import host as _host
from . import runtime as _runtime

_modules = (
    _registry, _helpers, _objects, _objects_player, _host_any, _host_collections, _host_engine, _host_gui, _host_objmethods, _host_particles, _host_vars, _host_bare, _host_objects, _host, _runtime,
)
_export_names = [
    'Any', 'ClientGS2', 'Dict', 'EMITTER_METHOD_NAMES',
    'FREEZE_MAX_TICKS', 'FREEZE_TICKS_PER_SECOND', 'GS2ClientHost', 'GS2Host',
    'GS2GuiManager', 'GS2Object', 'GS2VM', 'GS2_NULL',
    'GuiControl', 'GuiPopUpEditCtrl', 'List',
    'MODIFIER_METHOD_NAMES', 'NOT_HANDLED', 'Optional', 'PENDING_EVENT_CAP',
    'PLATFORM_NAME', 'PLAYER_ATTR', 'PLAYER_ATTR_COUNT', 'ParticleEmitter',
    'ParticleModifier', 'Path', 'SAVE_LINES_CACHE_MAX_BYTES', 'SAVE_LINES_MAX_CHARS_PER_LINE',
    'SAVE_LINES_MAX_LINES', 'SCHEDULED_EVENT_CAP', 'SimpleNamespace', 'TIMER_BACKLOG_CAP',
    'TIMER_RESOLUTION', 'UNSET', 'ZOOM_FACTOR_MAX', 'ZOOM_FACTOR_MIN',
    '_BoardTilesColumn', '_CanvasObject', '_DEFAULT_STAFF_GUILDS', '_EngineObject',
    '_FALL_THROUGH', '_FlagScopeObject', '_GANI_TRANSFORM_DEFAULTS', '_GS1_COMMANDS',
    '_GS1_FUNCTIONS', '_GS1_LEVEL_PROBES', '_GS1_PURE', '_GS1_TEXT_ARGS',
    '_GS2_ANY',
    '_GS2_BARE', '_GS2_BARE_GUI', '_GS2_ENGINE_METHODS', '_GS2_GLOBAL_SETTERS',
    '_GS2_GUI_METHODS', '_GS2_LIST_METHODS', '_GS2_OBJECTS', '_GS2_OBJ_METHODS',
    '_GS2_PARTICLE_METHODS', '_GS2_POPUP_METHODS', '_GS2_STR_METHODS', '_GS2_TABLES',
    '_GS2_VARS_METHODS', '_GaniThisObject', '_GlobalsStore', '_LayerImage',
    '_LevelObject', '_NPC_EMPTY_STRINGS', '_NPC_STRING_ATTRS', '_NPC_THIS_ATTR',
    '_NameObject', '_NpcColorsObject', '_NpcThisObject', '_PLATFORM_NAMES',
    '_PLAYER_EMPTY_STRINGS', '_PLAYER_MEMBER_ATTR', '_PLAYER_READONLY', '_PlayerAttrObject',
    '_PlayerColorsObject', '_PlayerObject', '_REMOTE_PLAYER_EMPTY_STRINGS', '_REMOTE_PLAYER_STICKY_NUMBERS',
    '_TIMER_CANCEL', '_ThisObject', '_WORD_BORDER', '_csv_flatten',
    '_csv_unflatten', '_engine_object', '_gs2_builtin', '_gs2_object',
    '_gs2_sort_key', '_guild_from_nick', '_image_size', '_is_admin_guild',
    '_set_lighting_enabled', '_set_selected_weapon',
    'annotations', 'board_tile_read',
    'board_tile_write', 'board_world_dims', 'emitter_for_record', 'gs2_casefold',
    'layer_image_get', 'logger', 'logging', 'math',
    'sys', 'time', 'to_bool', 'to_num',
    'to_str',
]
for _export_name in _export_names:
    for _module in _modules:
        if hasattr(_module, _export_name):
            globals()[_export_name] = getattr(_module, _export_name)
            break
    else:
        raise ImportError(f'missing GS2 client compatibility export: {_export_name}')

# NOTE: these are re-exported by VALUE, as in packets.py and gs1_client. Patching
# a name here (monkeypatch or otherwise) does NOT reach the submodule that reads
# it -- patch the owning module instead, e.g. pyreborn.gs2_client.runtime for
# GS2GuiManager / SAVE_LINES_CACHE_MAX_BYTES.
del _registry, _helpers, _objects, _objects_player
del _host_any, _host_collections, _host_engine, _host_gui
del _host_objmethods, _host_particles, _host_vars, _host_bare
del _host_objects, _host, _runtime
del _modules, _export_names, _export_name, _module
