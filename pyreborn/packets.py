"""Compatibility exports for the packet codec package.

Every non-dunder name defined in a packet_codec module is re-exported here,
so a new parser or builder needs no second edit. The first module (in the
order below) that owns a name wins, as it always did. `_NOT_EXPORTED` lists
the module-level names that deliberately stay out of this namespace.
"""

from .packet_codec import common as _common
from .packet_codec import level as _level
from .packet_codec import player as _player
from .packet_codec import gameplay as _gameplay
from .packet_codec import files as _files
from .packet_codec import rc as _rc
from .packet_codec import nc as _nc

_modules = (_common, _level, _player, _gameplay, _files, _rc, _nc)

# Names present in the codec modules that were never part of the packets
# namespace (shared-constant re-imports and module-private helpers).
_NOT_EXPORTED = frozenset({
    'COLORS_NEWWORLD', 'GUPD_BLOCKED_EXTENSIONS', 'GUPD_RESERVED_NAMES',
    'NPC_CLASS_NAME_MAX', 'Wire', 'Z_MAX_TILES', 'Z_MIN_TILES',
    '_CARRY_PLAYER_PROPS', '_MAP_IMAGE_EXTENSIONS', '_clean_server_text',
    '_map_number', '_parse_map_option', '_parse_moves',
    '_parse_named_bytecode_v4', '_set_carry', '_set_npc_classes',
    '_set_npc_equipment', '_set_npc_hurt_dxdy', '_set_npc_visflags',
    '_set_z2', '_shoot_angle_byte', '_shoot_zangle_byte', 'replace',
    'validate_server_warp_target', 'world_to_local',
})

for _module in _modules:
    for _export_name, _export_value in list(vars(_module).items()):
        if (_export_name.startswith('__') or _export_name in _NOT_EXPORTED
                or _export_name in globals()):
            continue
        globals()[_export_name] = _export_value
del _common, _level, _player, _gameplay, _files, _rc, _nc
del _modules, _module, _export_name, _export_value, _NOT_EXPORTED
