"""Client-side GS2 package component."""

from __future__ import annotations

from ..particles import EMITTER_METHOD_NAMES
from reborn_protocol.gs2 import GS2_NULL
from ..particles import MODIFIER_METHOD_NAMES
from ..particles import ParticleEmitter
from ..particles import ParticleModifier
from .registry import _FALL_THROUGH, _GS2_PARTICLE_METHODS, _gs2_builtin

class HostParticlesMixin:

    # -- _GS2_PARTICLE_METHODS: the particle-emitter object surface ----------
    # findimg(i).emitter's eight funcDefs (TParticleEmitterProperties
    # .cpp:259-332) and the modifier object's addmod (TParticleModifier
    # Properties.cpp:11-20); the state model lives in pyreborn/particles.py.

    @_gs2_builtin(_GS2_PARTICLE_METHODS, *sorted(EMITTER_METHOD_NAMES))
    def _particle_emitter_method(self, vm, name, args, obj):
        if not isinstance(obj, ParticleEmitter):
            return _FALL_THROUGH
        result = obj.call_method(name, list(args))
        if result is NotImplemented:
            return _FALL_THROUGH
        if result is None:
            # rejected modtype: the reference returns the null OBJECT, which
            # scripts test with `== null` -- 0.0 would compare unequal
            return GS2_NULL
        return result

    @_gs2_builtin(_GS2_PARTICLE_METHODS, *sorted(MODIFIER_METHOD_NAMES))
    def _particle_modifier_addmod(self, vm, name, args, obj):
        if not isinstance(obj, ParticleModifier):
            return _FALL_THROUGH
        obj.add_var_modifier(args[0] if args else "",
                             args[1] if len(args) > 1 else "",
                             args[2] if len(args) > 2 else 0.0,
                             args[3] if len(args) > 3 else 0.0)
        return 0.0
