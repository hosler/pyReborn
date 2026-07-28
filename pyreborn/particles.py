"""GS2 particle-emitter state model + simulation.

The v6 client hangs a lazily-created TParticleEmitter off every showimg
(FourPlay quattroplay/src/TShowImg.cpp:180-185); scripts configure it through
`findimg(i).emitter` and the three modifier lists (era/gta corpora, 14+
scripts).  This module is the engine-neutral state model: both script engines
(GS2 VM via gs2_client, era new-GS1 via gs1_client) resolve to the SAME
emitter object stored on the shared layer record, and the renderer
(game/render_effects.py) is a pure consumer of the state advanced here.

Oracle: quattroplay/src/TParticleEmitter.cpp, TParticleModifier.cpp,
TParticleData.cpp, TParticleEmitterProperties.cpp, TInitStatics.cpp:4744-4746.
"""
from __future__ import annotations

import math
import random
from typing import Any, List, Optional

from reborn_protocol.gs2 import GS2Object, to_num, to_str

#: The three name tables (TInitStatics.cpp:4744-4746), matched
#: case-insensitively; an unknown modtype rejects the whole call, an unknown
#: varname/mode keeps the modifier but silently skips the var effect
#: (TParticleEmitter.cpp:227-240, TParticleModifier.cpp:37-59).
MOD_TYPE_NAMES = ("once", "impulse", "range")
VAR_NAMES = ("x", "y", "z", "movex", "movey", "movez", "angle", "zangle",
             "speed", "rotation", "spin", "stretchx", "stretchy", "red",
             "green", "blue", "alpha", "zoom")
VAR_MODE_NAMES = ("replace", "add", "multiply")

#: list caps in the reference (TParticleEmitter.cpp:229, TParticleModifier
#: .cpp:39)
MODIFIER_CAP = 999
#: setNrofParticles / setMaxParticles clamps (TParticleEmitter.cpp:122-138)
NROF_CAP = 1000
MAXPARTICLES_CAP = 100000
#: setParticleTypeCount clamp (TParticleEmitter.cpp:149-153)
PARTICLE_TYPES_CAP = 100
#: local safety cap on LIVE particles, below maxparticles' 100000 default:
#: this client simulates in Python and must stay frame-rate-safe.
SIM_PARTICLE_CAP = 4000

_TWO_PI = 2.0 * math.pi
_HALF_PI = math.pi / 2.0


def _f(v) -> float:
    return float(to_num(v))


def _vector3(value) -> List[float]:
    """Coerce a script value ({x,y,z} array or CSV string) to 3 floats."""
    if isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = to_str(value).split(",") if to_str(value) else []
    out = [_f(p) for p in parts[:3]]
    while len(out) < 3:
        out.append(0.0)
    return out


def _getangle(dx: float, dy: float) -> float:
    # same convention as the shared GS1 getangle (screen Y flipped, [0, 2pi))
    if dx == 0.0 and dy == 0.0:
        return 0.0
    ang = math.atan2(-dy, dx)
    return ang + _TWO_PI if ang < 0 else ang


def _angles_to_vector(angle: float, zangle: float, speed: float):
    return (math.cos(angle) * math.cos(zangle) * speed,
            -math.sin(angle) * math.cos(zangle) * speed,
            math.sin(zangle) * speed)


class ParticleVarModifier:
    """One var effect of a modifier (TParticleVarModifier)."""

    __slots__ = ("type_index", "mode", "start_value", "end_value")

    def __init__(self, type_index: int, mode: int,
                 start_value: float, end_value: float):
        self.type_index = type_index
        self.mode = mode
        self.start_value = start_value
        self.end_value = end_value


class ParticleData:
    """Per-particle (and per-template) simulation state -- TParticleData.

    angle/zangle/speed and the movement vector are COUPLED exactly as the
    reference keeps them (TParticleData.cpp:91-153): writing any one
    recomputes the others.  Defaults per TParticleData::clear() (:26-50):
    vector (1,0,0) at speed 1, zoom/stretch/rgba 1, lifetime 0."""

    __slots__ = ("x", "y", "z", "vx", "vy", "vz", "angle", "zangle", "speed",
                 "rotation", "spin", "zoom", "stretchx", "stretchy",
                 "red", "green", "blue", "alpha", "mode", "image", "lifetime",
                 "born", "users")

    def __init__(self):
        self.x = self.y = self.z = 0.0
        self.vx, self.vy, self.vz = 1.0, 0.0, 0.0
        self.angle = 0.0
        self.zangle = 0.0
        self.speed = 1.0
        self.rotation = 0.0
        self.spin = 0.0
        self.zoom = 1.0
        self.stretchx = self.stretchy = 1.0
        self.red = self.green = self.blue = self.alpha = 1.0
        self.mode = 0.0
        self.image = ""
        self.lifetime = 0.0
        self.born = 0.0
        self.users: list = []

    def copy_from(self, other: "ParticleData") -> None:
        for slot in ("x", "y", "z", "vx", "vy", "vz", "angle", "zangle",
                     "speed", "rotation", "spin", "zoom", "stretchx",
                     "stretchy", "red", "green", "blue", "alpha", "mode",
                     "image", "lifetime"):
            setattr(self, slot, getattr(other, slot))

    # -- coupled movement fields (TParticleData.cpp:91-153) -----------------
    def set_movement_vector(self, vx: float, vy: float, vz: float) -> None:
        self.vx, self.vy, self.vz = vx, vy, vz
        if vx == 0.0 and vy == 0.0:
            if vz > 0.0:
                self.zangle = _HALF_PI
            elif vz < 0.0:
                self.zangle = -_HALF_PI
        else:
            self.angle = _getangle(vx, vy)
        flat = math.sqrt(vx * vx + vy * vy)
        if flat != 0.0 or vz != 0.0:
            # signed, stays inside +-pi/2 (flat is never negative)
            self.zangle = math.atan2(vz, flat)
        self.speed = math.sqrt(vx * vx + vy * vy + vz * vz)

    def set_speed(self, speed: float) -> None:
        if speed < 0.0:
            speed = 0.0
        if self.speed > 0.0:
            scale = speed / self.speed
            self.vx *= scale
            self.vy *= scale
            self.vz *= scale
        elif speed > 0.0:
            self.vx, self.vy, self.vz = _angles_to_vector(
                self.angle, self.zangle, speed)
        self.speed = speed

    def set_angle(self, angle: float) -> None:
        angle -= math.floor(angle / _TWO_PI) * _TWO_PI
        self.angle = angle
        if self.speed > 0.0:
            self.vx, self.vy, self.vz = _angles_to_vector(
                self.angle, self.zangle, self.speed)

    def set_zangle(self, zangle: float) -> None:
        self.zangle = max(-_HALF_PI, min(_HALF_PI, zangle))
        if self.speed > 0.0:
            self.vx, self.vy, self.vz = _angles_to_vector(
                self.angle, self.zangle, self.speed)

    def modify_value(self, type_index: int, mode: int, value: float) -> None:
        """Apply one var effect (TParticleData::modifyValue, :177-209):
        replace = assign, add = current+value, multiply = current*value.
        The stretch/colour family clamps at >= 0."""
        def apply(current: float) -> float:
            if mode == 1:
                return current + value
            if mode == 2:
                return current * value
            return value

        if type_index == 0:
            self.x = apply(self.x)
        elif type_index == 1:
            self.y = apply(self.y)
        elif type_index == 2:
            self.z = apply(self.z)
        elif type_index == 3:
            self.set_movement_vector(apply(self.vx), self.vy, self.vz)
        elif type_index == 4:
            self.set_movement_vector(self.vx, apply(self.vy), self.vz)
        elif type_index == 5:
            self.set_movement_vector(self.vx, self.vy, apply(self.vz))
        elif type_index == 6:
            self.set_angle(apply(self.angle))
        elif type_index == 7:
            self.set_zangle(apply(self.zangle))
        elif type_index == 8:
            self.set_speed(apply(self.speed))
        elif type_index == 9:
            self.rotation = apply(self.rotation)
        elif type_index == 10:
            self.spin = apply(self.spin)
        elif type_index == 11:
            self.stretchx = max(0.0, apply(self.stretchx))
        elif type_index == 12:
            self.stretchy = apply(self.stretchy)
        elif type_index == 13:
            self.red = max(0.0, apply(self.red))
        elif type_index == 14:
            self.green = max(0.0, apply(self.green))
        elif type_index == 15:
            self.blue = max(0.0, apply(self.blue))
        elif type_index == 16:
            self.alpha = max(0.0, apply(self.alpha))
        elif type_index == 17:
            self.zoom = apply(self.zoom)


class ParticleModifier(GS2Object):
    """One entry of a local/global/template modifier list (TParticleModifier).

    `user_time` is the SHARED timer used when this modifier runs from the
    global or template list; per-particle timers live on each particle's
    `users` list instead (TParticleEmitter.cpp:734-741)."""

    #: era new-GS1 with-scope member bridge (see gs1_client.get_builtin)
    gs1_with_members = True

    __slots__ = ("mod_type", "start_time", "end_time", "var_mods",
                 "user_time")

    def __init__(self, mod_type: int, start_time: float, end_time: float):
        super().__init__(name="TParticleModifier")
        self.mod_type = mod_type
        self.start_time = start_time
        self.end_time = end_time
        self.var_mods: List[ParticleVarModifier] = []
        self.user_time = 0.0

    def add_var_modifier(self, varname, mode, start_value, end_value) -> None:
        """addmod / the trailing 4 args of addXmodifier (TParticleModifier
        .cpp:37-59): unknown varname or mode -> silently no var effect."""
        if len(self.var_mods) > MODIFIER_CAP:
            return
        vname = to_str(varname).lower()
        mname = to_str(mode).lower()
        if vname not in VAR_NAMES or mname not in VAR_MODE_NAMES:
            return
        self.var_mods.append(ParticleVarModifier(
            VAR_NAMES.index(vname), VAR_MODE_NAMES.index(mname),
            _f(start_value), _f(end_value)))

    def process(self, data: ParticleData, user_time: float, keep_time: bool,
                now: float, scale: float) -> float:
        """One application step (TParticleModifier::process, :61-143).
        Returns the updated user timer (callers own where it is stored)."""
        if self.mod_type == 0:              # once: fires a single armed time
            if user_time > now or user_time == 0.0:
                return user_time
            for vm in self.var_mods:
                data.modify_value(vm.type_index, vm.mode, self._rand(vm))
            return user_time if keep_time else 0.0
        if self.mod_type == 1:              # impulse: refire + reschedule
            if now < user_time:
                return user_time
            for vm in self.var_mods:
                data.modify_value(vm.type_index, vm.mode, self._rand(vm))
            if keep_time:
                return user_time
            span = self.end_time - self.start_time
            return now + self.start_time + random.random() * span
        # range: active while elapsed is inside [start, end + 1e-6]
        elapsed = now - user_time
        if elapsed < self.start_time or elapsed > self.end_time + 1e-6:
            return user_time
        span = self.end_time - self.start_time
        for vm in self.var_mods:
            if span > 0.0:
                interp = ((elapsed - self.start_time)
                          * (vm.end_value - vm.start_value) / span
                          + vm.start_value)
            else:
                interp = vm.end_value
            if vm.mode == 1:                # add: dt-scaled interpolation
                if elapsed > self.end_time:
                    continue
                data.modify_value(vm.type_index, vm.mode, interp * scale)
            elif vm.mode == 2:              # multiply: constant end value
                data.modify_value(vm.type_index, vm.mode, vm.end_value)
            else:                           # replace: interpolate, then hold
                value = interp if elapsed < self.end_time else vm.end_value
                data.modify_value(vm.type_index, vm.mode, value)
        return user_time

    @staticmethod
    def _rand(vm: ParticleVarModifier) -> float:
        return (vm.start_value
                + random.random() * (vm.end_value - vm.start_value))

    # era new-GS1 method-call hook (interp._ex_MethodCall)
    def gs1_method(self, name: str, args: list):
        if name == "addmod":
            self.add_var_modifier(args[0] if args else "",
                                  args[1] if len(args) > 1 else "",
                                  args[2] if len(args) > 2 else 0.0,
                                  args[3] if len(args) > 3 else 0.0)
            return 0.0
        return NotImplemented


class ParticleTemplate(GS2Object):
    """One particle template -- the showimg-shaped objects in the emitter's
    `particles[]` array; `emitter.particle` is particles[0]
    (TParticleEmitterProperties.cpp:204-211, TParticleEmitter.cpp:79-90).
    Member writes seed every particle emitted from it."""

    gs1_with_members = True

    #: string-typed showimg properties (TShowImgProperties.cpp -- see
    #: gs2_client._LayerImage._SHOWIMG_STRINGS): unwritten ones must read as
    #: STRINGS, or an unanswered name compares equal to every word.
    _STRINGS = frozenset((
        "ani", "image", "font", "shadowoffset", "shadowcolor", "style",
        "text", "code", "position", "rotationcenter", "attachoffset",
        "movementvector", "sound",
    ))

    _NUM_ATTRS = {
        "x": "x", "y": "y", "z": "z", "lifetime": "lifetime", "zoom": "zoom",
        "stretchx": "stretchx", "stretchy": "stretchy", "red": "red",
        "green": "green", "blue": "blue", "alpha": "alpha", "mode": "mode",
        "rotation": "rotation", "spin": "spin",
    }

    __slots__ = ("data",)

    def __init__(self):
        super().__init__(name="particle")
        self.data = ParticleData()

    def has(self, key: str) -> bool:
        # get() computes these off self.data; claim them or the VM's
        # has()-gated with-stack skips this object inside
        # `with (emitter.particle) { ... }` (see ParticleEmitter.has)
        k = key.lower()
        return (k in self._NUM_ATTRS or k in self._STRINGS
                or k in ("angle", "zangle", "speed", "movementvector")
                or super().has(key))

    def get(self, key: str) -> Any:
        k = key.lower()
        attr = self._NUM_ATTRS.get(k)
        if attr is not None:
            return float(getattr(self.data, attr))
        if k in ("angle", "zangle", "speed"):
            return float(getattr(self.data, k))
        if k == "movementvector":
            return [self.data.vx, self.data.vy, self.data.vz]
        if k == "image":
            return self.data.image
        value = super().get(key)
        if value is None and k in self._STRINGS:
            return ""
        return value

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        attr = self._NUM_ATTRS.get(k)
        if attr is not None:
            setattr(self.data, attr, _f(value))
            return
        if k == "angle":
            self.data.set_angle(_f(value))
            return
        if k == "zangle":
            self.data.set_zangle(_f(value))
            return
        if k == "speed":
            self.data.set_speed(_f(value))
            return
        if k == "movementvector":
            self.data.set_movement_vector(*_vector3(value))
            return
        if k == "image":
            self.data.image = to_str(value)
            return
        super().set(key, value)

    def copy_from_template(self, other: "ParticleTemplate") -> None:
        self.data.copy_from(other.data)
        for key in list(other._members):
            self._members[key] = other._members[key]


#: emitter flag/scalar properties with reference defaults
#: (TParticleEmitter constructor, TParticleEmitter.cpp:37-110)
_EMITTER_NUMS = {
    "attachposition": 0.0, "autorotation": 0.0, "checkbelowterrain": 0.0,
    "cliptoscreen": 0.0, "continueafterdestroy": 0.0,
    "emitatterrainheight": 0.0, "emitautomatically": 1.0,
    "firstinfront": 1.0, "forceaboveterrain": 0.0, "isfrozen": 0.0,
    "noclipping": 0.0, "showonground": 0.0, "showontop": 0.0,
    "switchyandzaxis": 0.0, "wraptoclippingbox": 0.0,
    "delaymin": 1.0, "delaymax": 1.0, "movementfactor": 0.0,
}

#: propDefs entries with a nullptr setter (TParticleEmitterProperties.cpp)
#: plus the constructor-built `particles` child: writes are ignored.
_EMITTER_READONLY = frozenset((
    "currentparticlecount", "emittedparticles", "particle", "particles",
    "dropemitter", "dropwateremitter",
))

#: the eight funcDefs (TParticleEmitterProperties.cpp:259-332)
EMITTER_METHOD_NAMES = frozenset((
    "addglobalmodifier", "addlocalmodifier", "addemitmodifier",
    "advancetime", "emit", "emitat", "removemodifiers", "removeparticles",
))

MODIFIER_METHOD_NAMES = frozenset(("addmod",))


class ParticleEmitter(GS2Object):
    """The `findimg(i).emitter` object: full 28-property surface plus the
    particle simulation. Hangs off the SHARED layer record so the GS1 and
    GS2 engines (and the renderer) all see one emitter."""

    gs1_with_members = True

    __slots__ = ("rec", "templates", "local_modifiers", "global_modifiers",
                 "template_modifiers", "particles", "emitted_total",
                 "_now", "_last_emit", "_delay", "_nrofparticles",
                 "_maxparticles", "_dropemitter", "_dropwateremitter")

    def __init__(self, rec: Optional[dict] = None):
        super().__init__(name="TParticleEmitter")
        self.rec = rec if rec is not None else {}
        for key, default in _EMITTER_NUMS.items():
            self._members[key] = default
        self._members["clippingbox"] = ""
        self._members["emissionoffset"] = [0.0, 0.0, 0.0]
        self.templates: List[ParticleTemplate] = [ParticleTemplate()]
        self.local_modifiers: List[ParticleModifier] = []
        self.global_modifiers: List[ParticleModifier] = []
        self.template_modifiers: List[ParticleModifier] = []
        self.particles: List[ParticleData] = []
        self.emitted_total = 0
        # sim clock starts >0 so a first-frame emission's `once` modifiers
        # arm (user time 0 means "disabled" in the reference)
        self._now = 1.0
        self._last_emit: Optional[float] = None
        self._delay = 0.0
        self._nrofparticles = 0
        self._maxparticles = MAXPARTICLES_CAP
        self._dropemitter: Optional[ParticleEmitter] = None
        self._dropwateremitter: Optional[ParticleEmitter] = None

    #: property names get() COMPUTES off the simulation state (the flag/
    #: scalar properties are seeded into _members by __init__ and answer
    #: through the base class). has() must claim them because the GS2 VM's
    #: with-stack resolution is has()-gated (vm._lookup/_assign_name): an
    #: unclaimed name inside `with (<emitter>) { nrofparticles = 50; }`
    #: silently writes a VM global instead and the emitter never emits.
    _COMPUTED_PROPS = frozenset((
        "particle", "particles", "particletypes", "nrofparticles",
        "maxparticles", "currentparticlecount", "emittedparticles",
        "dropemitter", "dropwateremitter",
    ))

    def has(self, key: str) -> bool:
        return key.lower() in self._COMPUTED_PROPS or super().has(key)

    # -- property surface ---------------------------------------------------
    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "particle":
            return self.templates[0]
        if k == "particles":
            return self.templates
        if k == "particletypes":
            return float(len(self.templates))
        if k == "nrofparticles":
            return float(self._nrofparticles)
        if k == "maxparticles":
            return float(self._maxparticles)
        if k == "currentparticlecount":
            return float(len(self.particles))
        if k == "emittedparticles":
            return float(self.emitted_total)
        if k == "dropemitter":
            return self._drop_emitter("_dropemitter")
        if k == "dropwateremitter":
            return self._drop_emitter("_dropwateremitter")
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k in _EMITTER_READONLY:
            return
        if k == "nrofparticles":
            self._nrofparticles = max(0, min(NROF_CAP, int(_f(value))))
            return
        if k == "maxparticles":
            self._maxparticles = max(0, min(MAXPARTICLES_CAP, int(_f(value))))
            return
        if k == "particletypes":
            self._set_particle_types(int(_f(value)))
            return
        if k == "emissionoffset":
            self._members[k] = _vector3(value)
            return
        if k == "isfrozen":
            was = self._members.get("isfrozen", 0.0) != 0.0
            frozen = _f(value) != 0.0
            self._members["isfrozen"] = 1.0 if frozen else 0.0
            if was and not frozen:
                # unfreeze re-arms the emit clock (TParticleEmitter.cpp:140-147)
                self._last_emit = None
            return
        if k in _EMITTER_NUMS:
            self._members[k] = _f(value)
            return
        super().set(key, value)

    def _drop_emitter(self, slot: str) -> "ParticleEmitter":
        # lazily created, never emits automatically (TParticleEmitter
        # .cpp:377-393)
        sub = getattr(self, slot)
        if sub is None:
            sub = ParticleEmitter(self.rec)
            sub.set("emitautomatically", 0.0)
            setattr(self, slot, sub)
        return sub

    def _set_particle_types(self, count: int) -> None:
        # grow copies template[0] into the new slots (TParticleEmitter
        # .cpp:149-225)
        count = 1 if count <= 0 else min(count, PARTICLE_TYPES_CAP)
        while len(self.templates) > count:
            self.templates.pop()
        while len(self.templates) < count:
            tpl = ParticleTemplate()
            tpl.copy_from_template(self.templates[0])
            self.templates.append(tpl)

    # -- modifier surface ---------------------------------------------------
    def _add_modifier(self, target: List[ParticleModifier],
                      args: list) -> Optional[ParticleModifier]:
        """The 7-arg addXmodifier(modtype, start, end, varname, mode, sv, ev):
        unknown modtype -> None (script-visible null), list capped at 999."""
        if len(target) > MODIFIER_CAP:
            return None
        modtype = to_str(args[0] if args else "").lower()
        if modtype not in MOD_TYPE_NAMES:
            return None
        modifier = ParticleModifier(
            MOD_TYPE_NAMES.index(modtype),
            _f(args[1]) if len(args) > 1 else 0.0,
            _f(args[2]) if len(args) > 2 else 0.0)
        modifier.add_var_modifier(
            args[3] if len(args) > 3 else "",
            args[4] if len(args) > 4 else "",
            args[5] if len(args) > 5 else 0.0,
            args[6] if len(args) > 6 else 0.0)
        target.append(modifier)
        return modifier

    def add_local_modifier(self, args: list) -> Optional[ParticleModifier]:
        return self._add_modifier(self.local_modifiers, args)

    def add_global_modifier(self, args: list) -> Optional[ParticleModifier]:
        return self._add_modifier(self.global_modifiers, args)

    def add_template_modifier(self, args: list) -> Optional[ParticleModifier]:
        return self._add_modifier(self.template_modifiers, args)

    def remove_modifiers(self) -> None:
        # drops all three lists AND the live particles
        # (TParticleEmitter.cpp:272-281)
        self.template_modifiers = []
        self.global_modifiers = []
        self.local_modifiers = []
        self.remove_particles()

    def remove_particles(self) -> None:
        self.particles = []

    # -- emission + simulation ----------------------------------------------
    def _owner_position(self):
        rec = self.rec
        return (_f(rec.get("x", 0.0)), _f(rec.get("y", 0.0)),
                _f(rec.get("z", 0.0)))

    def emit_now(self, position=None, now: Optional[float] = None) -> None:
        """TParticleEmitter::emit (:667-755). `position` is in the owner
        record's coordinate frame; None = the owner's own position."""
        if now is None:
            now = self._now
        if position is None:
            position = self._owner_position()
        count = min(self._nrofparticles,
                    self._maxparticles - len(self.particles),
                    SIM_PARTICLE_CAP - len(self.particles))
        if count < 1 or not self.templates:
            return
        offx, offy, offz = _vector3(self._members.get("emissionoffset"))
        factor = self._members.get("movementfactor", 0.0)
        attach = self._members.get("attachposition", 0.0) != 0.0
        terrain = self._members.get("emitatterrainheight", 0.0) != 0.0
        ox, oy, oz = self._owner_position()
        for _ in range(count):
            template = (self.templates[0] if len(self.templates) == 1
                        else random.choice(self.templates))
            p = ParticleData()
            p.copy_from(template.data)
            p.born = now
            if factor == 0.0:
                px, py, pz = offx, offy, offz
            else:
                # rotate the offset by movementfactor (:706-717)
                ang = _getangle(offx, offy) + factor
                spd = math.sqrt(offx * offx + offy * offy)
                px = math.cos(ang) * spd
                py = -math.sin(ang) * spd
                pz = offz
            if attach:
                px += position[0] - ox
                py += position[1] - oy
                pz += position[2] - oz
            else:
                px += position[0]
                py += position[1]
                if not terrain:
                    pz += position[2]
            p.x, p.y, p.z = px, py, pz
            p.users = [[mod, now] for mod in self.local_modifiers]
            # addParticle processNow (TParticleEmitter.cpp:330-355): one
            # zero-dt process at emit, so `once` modifiers land before the
            # particle is ever drawn
            for user in p.users:
                user[1] = user[0].process(p, user[1], False, now, 0.0)
            for mod in self.global_modifiers:
                mod.process(p, mod.user_time, True, now, 0.0)
            self.particles.append(p)
            self.emitted_total += 1

    def advance(self, dt: float) -> None:
        """Advance the simulation clock (TParticleEmitter::process, :1138-
        1188): automatic emission cadence, template/local/global modifiers,
        movement integration, lifetime expiry, global timer updates."""
        if self._members.get("isfrozen", 0.0) != 0.0:
            return
        dt = max(0.0, _f(dt))
        self._now += dt
        now = self._now
        emit_due = False
        if self._members.get("emitautomatically", 0.0) != 0.0:
            if self._last_emit is None:
                self._last_emit = now
                self._delay = self._pick_delay()
            elif now - self._last_emit >= self._delay:
                emit_due = True
                self._last_emit = now
                self._delay = self._pick_delay()
        self._process_templates(now, dt)
        autorotate = self._members.get("autorotation", 0.0) != 0.0
        if len(self.particles) > self._maxparticles:
            del self.particles[:len(self.particles) - self._maxparticles]
        survivors = []
        for p in self.particles:
            if self._process_particle(p, now, dt, autorotate):
                survivors.append(p)
        self.particles = survivors
        self._update_global_timers(now)
        if emit_due:
            self.emit_now(now=now)
        if self._dropemitter is not None:
            self._dropemitter.advance(dt)
        if self._dropwateremitter is not None:
            self._dropwateremitter.advance(dt)

    def _pick_delay(self) -> float:
        lo = self._members.get("delaymin", 1.0)
        hi = self._members.get("delaymax", 1.0)
        return lo + random.random() * (hi - lo)

    def _process_templates(self, now: float, dt: float) -> None:
        # template/emit modifiers mutate the TEMPLATES so future emissions
        # inherit (TParticleEmitter::processTemplateModifiers, :443-463)
        for template in self.templates:
            for mod in self.template_modifiers:
                mod.user_time = mod.process(
                    template.data, mod.user_time, False, now, dt)

    def _process_particle(self, p: ParticleData, now: float, dt: float,
                          autorotate: bool) -> bool:
        """One step; False = expired (order per processParticle/
        processParticle2, :465-665: expiry first, then local users, then
        globals -- shared timer, kept)."""
        if now - p.born >= p.lifetime:
            self._drop_cascade(p, now)
            return False
        for user in p.users:
            user[1] = user[0].process(p, user[1], False, now, dt)
        for mod in self.global_modifiers:
            mod.process(p, mod.user_time, True, now, dt)
        p.x += p.vx * dt
        p.y += p.vy * dt
        p.z += p.vz * dt
        if autorotate:
            p.rotation = p.angle
        elif p.spin != 0.0:
            p.rotation += p.spin * dt
        return True

    def _drop_cascade(self, p: ParticleData, now: float) -> None:
        # an expired particle feeds the drop emitters (:629-665); the water
        # tile test is render-level state this model does not carry, so a
        # created dropwateremitter takes precedence
        sub = self._dropwateremitter or self._dropemitter
        if sub is not None:
            sub.emit_now(position=(p.x, p.y, p.z), now=now)

    def _update_global_timers(self, now: float) -> None:
        # TParticleEmitter::updateGlobalModifierTimers (:414-441)
        for mod in self.global_modifiers:
            if mod.mod_type == 2:
                mod.user_time = 0.0
            elif now >= mod.user_time:
                if mod.mod_type == 0:
                    mod.user_time = 0.0
                else:
                    span = mod.end_time - mod.start_time
                    mod.user_time = (now + mod.start_time
                                     + random.random() * span)

    # -- script method entry points -----------------------------------------
    def call_method(self, name: str, args: list) -> Any:
        """Dispatch one of the eight funcDefs; returns the modifier object,
        None for a rejected modtype (the host maps that to GS2 null), or 0.0
        for the void methods."""
        if name == "addlocalmodifier":
            return self.add_local_modifier(args)
        if name == "addglobalmodifier":
            return self.add_global_modifier(args)
        if name == "addemitmodifier":
            return self.add_template_modifier(args)
        if name == "advancetime":
            self.advance(_f(args[0]) if args else 0.0)
            return 0.0
        if name == "emit":
            self.emit_now()
            return 0.0
        if name == "emitat":
            self.emit_now(position=_vector3(args[0] if args else ""))
            return 0.0
        if name == "removemodifiers":
            self.remove_modifiers()
            return 0.0
        if name == "removeparticles":
            self.remove_particles()
            return 0.0
        return NotImplemented

    # era new-GS1 method-call hook (interp._ex_MethodCall)
    def gs1_method(self, name: str, args: list):
        if name not in EMITTER_METHOD_NAMES:
            return NotImplemented
        result = self.call_method(name, args)
        # GS1 has no null object entry; a rejected modtype reads 0.0 there
        return 0.0 if result is None or result is NotImplemented else result


def emitter_for_record(rec: dict) -> ParticleEmitter:
    """The lazy, identity-stable `showimg.emitter` getter
    (TShowImg::getParticleEmitter, TShowImg.cpp:180-185)."""
    emitter = rec.get("emitter")
    if not isinstance(emitter, ParticleEmitter) or emitter.rec is not rec:
        emitter = rec["emitter"] = ParticleEmitter(rec)
    return emitter
